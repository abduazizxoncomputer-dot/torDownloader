import asyncio
import logging
import re
from pathlib import Path

from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter

from telegram_bot import config, userbot
from telegram_bot.progress import format_upload_done, format_upload_progress

logger = logging.getLogger(__name__)

_UPLOAD_TIMEOUTS = dict(read_timeout=600, write_timeout=600, connect_timeout=60, pool_timeout=60)

_RETRY_AFTER_PATTERN = re.compile(r'retry after (\d+)', re.IGNORECASE)

# Ketma-ket fayl yuborishlar orasidagi kichik pauza — Telegramning
# chat-darajasidagi flood-limitiga (~1 xabar/soniya) tegib qolish ehtimolini
# kamaytiradi. _with_flood_retry bu limitga baribir tegib qolgan holatni
# qamrab oladi.
INTER_FILE_DELAY_SECONDS = 1.5


async def with_flood_retry(make_coro, max_retries=3):
    """`make_coro` (argumentsiz, har chaqirilganda YANGI coroutine qaytaradigan
    callable) ni bajaradi; Telegramning flood-limiti (RetryAfter, yoki matnida
    'retry after N' bo'lgan BadRequest) tegib qolsa, ko'rsatilgan vaqtcha kutib
    avtomatik qayta urinadi."""
    for attempt in range(max_retries + 1):
        try:
            return await make_coro()
        except RetryAfter as exc:
            wait_s = exc.retry_after
        except BadRequest as exc:
            match = _RETRY_AFTER_PATTERN.search(str(exc))
            if not match:
                raise
            wait_s = int(match.group(1))
        if attempt == max_retries:
            raise
        logger.warning("Flood-limitga tegildi, %ss kutilmoqda (urinish %d/%d)", wait_s, attempt + 1, max_retries)
        await asyncio.sleep(wait_s + 1)


class UploadProgressReporter:
    """Tracks upload progress across a batch of files and periodically edits
    a single Telegram message with it, mirroring the download progress bar.

    Byte-level position is only reported live where the underlying transport
    actually gives it to us (the Pyrogram userbot relay); direct Bot API
    sends and split-file parts advance the bar in whole-file/whole-part
    steps instead, since python-telegram-bot reads the file fully before
    the network transfer starts."""

    def __init__(self, bot, chat_id, message_id, total_bytes, interval=None):
        self._bot = bot
        self._chat_id = chat_id
        self._message_id = message_id
        self._total_bytes = total_bytes
        self._sent_bytes = 0
        self._current_name = ''
        self._current_done = 0
        self._current_total = 0
        self._interval = interval or config.PROGRESS_EDIT_INTERVAL_SECONDS
        self._last_text = None
        self._task = None

    async def begin_file(self, name, size):
        self._current_name = name
        self._current_total = size
        self._current_done = 0
        # Awaited directly (not left to the background ticker) so the
        # "Yuborilmoqda..." status is guaranteed to post before the upload
        # itself starts. PTB reads the whole file into memory synchronously
        # before its first real network await, which can starve the ticker
        # task of a chance to run before a fast/local upload already finishes.
        await self._render()

    def report(self, current, total=None):
        self._current_done = current
        if total:
            self._current_total = total

    async def finish_file(self):
        name = self._current_name or 'Fayl'
        self._sent_bytes += self._current_total
        self._current_done = 0
        self._current_total = 0
        # Direct Bot API sends never report live progress (see class
        # docstring), so without this the message would stay frozen on its
        # last "Yuborilmoqda..." text forever even though the file is done.
        await self._edit(format_upload_done(name))

    async def _render(self):
        done = self._sent_bytes + self._current_done
        text = format_upload_progress(self._current_name or 'Fayl', done, self._total_bytes)
        await self._edit(text)

    async def _edit(self, text):
        if text == self._last_text:
            return
        self._last_text = text
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=self._message_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except BadRequest as exc:
            if 'not modified' not in str(exc).lower():
                logger.warning("Failed to edit upload progress message: %s", exc)

    async def _tick(self):
        while True:
            await asyncio.sleep(self._interval)
            await self._render()

    def start(self):
        self._task = asyncio.create_task(self._tick())

    async def stop(self):
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass


def find_downloaded_files(save_path):
    root = Path(save_path)
    return sorted(p for p in root.rglob('*') if p.is_file())


def split_file(path: Path, chunk_size: int):
    """Splits `path` into sequential chunk_size-byte parts next to the
    original file, then removes the original. Returns the list of part
    paths in order."""
    parts = []
    with open(path, 'rb') as source:
        index = 1
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            part_path = path.with_name(f"{path.name}.part{index:03d}")
            with open(part_path, 'wb') as part_file:
                part_file.write(chunk)
            parts.append(part_path)
            index += 1
    path.unlink(missing_ok=True)
    return parts


_TITLE_CUT_PATTERN = re.compile(
    r'(?<!\d)(19|20)\d{2}(?!\d)'
    r'|\b(4k|2160p|1080p|720p|480p|360p|blu-?ray|brrip|bdrip|webrip|web-?dl|hdtv|dvdrip|dvdscr'
    r'|hdcam|hdrip|hqcam|telesync|x264|x265|h\.?264|h\.?265|hevc|xvid|avc|dual[.\-]?audio'
    r'|aac|ac3|dts|10bit|8bit|6ch|5\.1|7\.1|repack|proper|extended|remastered|uncut|multi|nf|amzn|hulu|dsnp)\b',
    re.IGNORECASE,
)


def _extract_title(filename, strip_text=None):
    """Fayl nomidan toza sarlavhani ajratib oladi.

    Agar `strip_text` berilgan bo'lsa (foydalanuvchi jobning birinchi fayli
    uchun qaysi qismni olib tashlashni aytgan bo'lsa), aynan o'sha matn
    olib tashlanadi — bu matn odatda bir xil release-teg bo'lgani uchun
    jobning qolgan fayllariga ham qayta so'ramasdan qo'llanadi.

    Aks holda, torrent-uslubidagi nomdan (nuqta bilan ajratilgan, yil/sifat/
    manba/kodek teglari bilan to'la) birinchi uchragan yil (19xx/20xx) yoki
    release-teg (720p, BluRay, x264 va h.k.) dan oldingi qismni oladi. Misol:
    'The.Legend.of.Korra.S01E01-E02.720p.HDTV.x264-HWE.mkv' -> 'The.Legend.of.Korra.S01E01-E02'."""
    stem = Path(filename).stem
    if strip_text:
        return stem.replace(strip_text, '').rstrip('. -_') or stem
    match = _TITLE_CUT_PATTERN.search(stem)
    title = stem[:match.start()] if match else stem
    return title.rstrip('. -_') or stem


def _build_caption(filename, part_label=None, title_strip=None):
    title = _extract_title(filename, strip_text=title_strip)
    if part_label:
        title = f"{title} — {part_label}"
    title = title.upper()
    return (
        f"<b>{title}</b>\n\n"
        f"<b>Telegram bot to order movie</b>\n@orderMovies_bot\n\n"
        f'<b><a href="{config.ORDER_CHANNEL_URL}">ORDERED MOVIES</a></b>'
    )


def _join_instructions(original_name, part_names):
    windows_cmd = "copy /b " + "+".join(part_names) + f" \"{original_name}\""
    unix_cmd = "cat " + " ".join(f'"{p}"' for p in part_names) + f' > "{original_name}"'
    return (
        f"🧩 <b>{original_name}</b> — split into {len(part_names)} parts.\n\n"
        "To join them back into one file:\n\n"
        "1️⃣ Download all the parts above (part001, part002, ...).\n"
        "2️⃣ Put them all in the same folder.\n"
        "3️⃣ Open a terminal/command prompt in that folder and run:\n\n"
        f"🪟 <b>Windows</b> (cmd / PowerShell):\n<code>{windows_cmd}</code>\n\n"
        f"🐧 <b>Linux / macOS</b> (terminal):\n<code>{unix_cmd}</code>\n\n"
        f"✅ The result will be <b>{original_name}</b> — the original video file."
    )


async def _send_one(bot, chat_id, path: Path, caption=None):
    async def attempt():
        with open(path, 'rb') as fh:
            await bot.send_document(
                chat_id=chat_id,
                document=fh,
                filename=path.name,
                caption=caption,
                parse_mode=ParseMode.HTML if caption else None,
                **_UPLOAD_TIMEOUTS,
            )
    await with_flood_retry(attempt)


async def deliver_file(bot, chat_id, path: Path, reporter: UploadProgressReporter, title_strip=None):
    size = path.stat().st_size
    await reporter.begin_file(path.name, size)

    if size <= config.BOT_UPLOAD_LIMIT_BYTES:
        await _send_one(bot, chat_id, path, caption=_build_caption(path.name, title_strip=title_strip))
        await reporter.finish_file()
        return

    if userbot.is_enabled() and size <= config.USERBOT_UPLOAD_LIMIT_BYTES:
        logger.info("Relaying %s (%.1f MB) via userbot", path, size / 1024 / 1024)
        await userbot.relay_large_file(
            bot, chat_id, path,
            caption=_build_caption(path.name, title_strip=title_strip),
            progress=reporter.report,
        )
        await reporter.finish_file()
        return

    logger.info("Splitting %s (%.1f MB) into %d MB chunks", path, size / 1024 / 1024, config.CHUNK_SIZE_MB)
    parts = split_file(path, config.CHUNK_SIZE_BYTES)
    part_names = [p.name for p in parts]
    for i, part in enumerate(parts, start=1):
        caption = _build_caption(path.name, part_label=f"part {i}/{len(parts)}", title_strip=title_strip)
        await reporter.begin_file(f"{path.name} ({i}/{len(parts)})", part.stat().st_size)
        await _send_one(bot, chat_id, part, caption=caption)
        await reporter.finish_file()
        part.unlink(missing_ok=True)

    await bot.send_message(
        chat_id=chat_id,
        text=_join_instructions(path.name, part_names),
        parse_mode=ParseMode.HTML,
    )


async def deliver_single_file(bot, chat_id, message_id, path: Path, title_strip=None):
    """Bitta faylni yuboradi va muvaffaqiyatli yetkazilgach uni (va endi
    bo'sh qolgan job papkasini) serverdan o'chiradi — /files ro'yxatidan
    bitta faylni tanlab qayta yuborishda ishlatiladi."""
    size = path.stat().st_size
    reporter = UploadProgressReporter(bot, chat_id, message_id, size)
    reporter.start()
    try:
        await deliver_file(bot, chat_id, path, reporter, title_strip=title_strip)
    finally:
        await reporter.stop()

    if not config.KEEP_FILES_AFTER_SEND:
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass

