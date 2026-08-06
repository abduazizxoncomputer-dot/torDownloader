import asyncio
import logging
import os
import shutil
from pathlib import Path

from telegram.constants import ParseMode
from telegram.error import BadRequest

from telegram_bot import config, userbot
from telegram_bot.progress import format_upload_progress

logger = logging.getLogger(__name__)

_UPLOAD_TIMEOUTS = dict(read_timeout=600, write_timeout=600, connect_timeout=60, pool_timeout=60)


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

    def begin_file(self, name, size):
        self._current_name = name
        self._current_total = size
        self._current_done = 0

    def report(self, current, total=None):
        self._current_done = current
        if total:
            self._current_total = total

    def finish_file(self):
        self._sent_bytes += self._current_total
        self._current_done = 0
        self._current_total = 0

    async def _tick(self):
        while True:
            await asyncio.sleep(self._interval)
            done = self._sent_bytes + self._current_done
            text = format_upload_progress(self._current_name or 'Fayl', done, self._total_bytes)
            if text == self._last_text:
                continue
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


def _join_instructions(part_names):
    windows_cmd = "copy /b " + "+".join(part_names) + f" {part_names[0].rsplit('.part', 1)[0]}"
    unix_cmd = "cat " + " ".join(part_names) + f" > {part_names[0].rsplit('.part', 1)[0]}"
    return (
        "⚠️ Fayl hajmi kattaligi sabab qismlarga bo'lindi. Barcha qismlarni yuklab, "
        "bitta papkaga joylab, birlashtiring:\n\n"
        f"Windows:\n<code>{windows_cmd}</code>\n\n"
        f"Linux/macOS:\n<code>{unix_cmd}</code>"
    )


async def _send_one(bot, chat_id, path: Path, caption=None):
    with open(path, 'rb') as fh:
        await bot.send_document(
            chat_id=chat_id,
            document=fh,
            filename=path.name,
            caption=caption,
            parse_mode=ParseMode.HTML if caption else None,
            **_UPLOAD_TIMEOUTS,
        )


async def deliver_file(bot, chat_id, path: Path, reporter: UploadProgressReporter):
    size = path.stat().st_size
    reporter.begin_file(path.name, size)

    if size <= config.BOT_UPLOAD_LIMIT_BYTES:
        await _send_one(bot, chat_id, path)
        reporter.finish_file()
        return

    if userbot.is_enabled() and size <= config.USERBOT_UPLOAD_LIMIT_BYTES:
        logger.info("Relaying %s (%.1f MB) via userbot", path, size / 1024 / 1024)
        await userbot.relay_large_file(bot, chat_id, path, progress=reporter.report)
        reporter.finish_file()
        return

    logger.info("Splitting %s (%.1f MB) into %d MB chunks", path, size / 1024 / 1024, config.CHUNK_SIZE_MB)
    parts = split_file(path, config.CHUNK_SIZE_BYTES)
    part_names = [p.name for p in parts]
    for i, part in enumerate(parts, start=1):
        caption = f"{path.name} — qism {i}/{len(parts)}"
        if i == len(parts):
            caption += "\n\n" + _join_instructions(part_names)
        reporter.begin_file(f"{path.name} ({i}/{len(parts)})", part.stat().st_size)
        await _send_one(bot, chat_id, part, caption=caption)
        reporter.finish_file()
        part.unlink(missing_ok=True)


async def deliver_job_files(bot, chat_id, message_id, save_path):
    files = find_downloaded_files(save_path)
    if not files:
        raise RuntimeError("Yuklangan fayllar topilmadi.")

    total_bytes = sum(p.stat().st_size for p in files)
    reporter = UploadProgressReporter(bot, chat_id, message_id, total_bytes)
    reporter.start()
    try:
        for file_path in files:
            await deliver_file(bot, chat_id, file_path, reporter)
    finally:
        await reporter.stop()

    if not config.KEEP_FILES_AFTER_SEND:
        shutil.rmtree(save_path, ignore_errors=True)
