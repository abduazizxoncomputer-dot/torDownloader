import asyncio
import logging
import shutil
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from telegram_bot import config
from telegram_bot.file_delivery import INTER_FILE_DELAY_SECONDS, deliver_single_file, find_downloaded_files, with_flood_retry
from telegram_bot.jobs import DownloadManager
from telegram_bot.progress import format_done, format_error, format_progress, human_size
from telegram_bot.runner import run_job_sync

logger = logging.getLogger(__name__)

# chat_id -> Future kutayotgan "nomdan nima olib tashlansin" javobi uchun.
_pending_title_prompts: dict = {}

WELCOME = (
    "🎬 <b>Hello! I'm a torrent download bot.</b>\n\n"
    "📥 <b>How I work:</b>\n"
    "1️⃣ Send me a magnet link or a <code>.torrent</code> file.\n"
    "2️⃣ I'll download the torrent to the server — you'll see a progress bar "
    "(⏸ Pause / ▶️ Resume / ⏹ Stop buttons are available).\n"
    "3️⃣ Once it's downloaded, I'll ask what unwanted part to remove from the "
    "file name (e.g. <code>720p.HDTV.x264-HWE</code>) — if your reply covers "
    "several parts (episodes), it's applied to all of them without asking again. "
    "Send /skip to continue without changing the name.\n"
    "4️⃣ I'll send you each file separately with its own progress bar, and "
    "delete it from the server right after it's successfully delivered.\n\n"
    "📦 <b>About file size:</b>\n"
    "• Up to ~1900MB — sent directly.\n"
    "• Larger — automatically split into parts (part001, part002, ...), and "
    "I'll send instructions for joining them back together at the end.\n"
    "• ~2000MB is Telegram's own limit — it can't be bypassed by any method.\n\n"
    "🕹 <b>Commands:</b>\n"
    "/start or /help — this guide\n"
    "/status — list of currently active (downloading) torrents, with progress\n"
    "/files — list of files left on the server after a failed delivery — "
    "each one can be resent or deleted individually\n"
    "/skip — continue without answering the name-cleanup prompt\n\n"
    "🗑 If a file isn't sent or deleted within 12 hours, the server "
    "automatically cleans it up."
)


def _manager(context: ContextTypes.DEFAULT_TYPE) -> DownloadManager:
    return context.application.bot_data['manager']


def _keyboard(job_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⏸ Pause", callback_data=f"pause:{job_id}"),
        InlineKeyboardButton("▶️ Resume", callback_data=f"resume:{job_id}"),
        InlineKeyboardButton("⏹ Stop", callback_data=f"stop:{job_id}"),
    ]])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = _manager(context)
    jobs = manager.jobs_for_chat(update.effective_chat.id)
    if not jobs:
        await update.message.reply_text("No active downloads.")
        return

    lines = []
    for job in jobs:
        name = job.status.get('name') or job.source[:40]
        total = job.status.get('total_wanted') or 0
        done = job.status.get('total_done') or 0
        percent = (done / total * 100) if total else 0.0
        lines.append(f"• {name} — {percent:.1f}%")
    await update.message.reply_text("\n".join(lines))


def _is_valid_job_id(job_id):
    return len(job_id) == 8 and all(c in '0123456789abcdef' for c in job_id)


def _resolve_file(chat_dir, job_id, index_str):
    """`job_id:index` callback-payload'ini haqiqiy fayl yo'liga aylantiradi.
    job_id formati (8 ta hex belgi) tekshiriladi — chat_dir tashqarisiga
    (path traversal) chiqib ketishning oldini olish uchun."""
    if not _is_valid_job_id(job_id) or not index_str.isdigit():
        return None
    folder = chat_dir / job_id
    if not folder.is_dir():
        return None
    files = find_downloaded_files(folder)
    index = int(index_str)
    return files[index] if 0 <= index < len(files) else None


# Telegram xabarlari ~4096 belgigacha bo'ladi; fayllar ko'p bo'lsa bitta
# xabarga sig'dirishga urinish "Message is too long" bilan qulaydi — shuning
# uchun sahifalarga bo'lamiz.
_FILES_PER_PAGE = 20


def _build_files_list_pages(context: ContextTypes.DEFAULT_TYPE, chat_id):
    """Serverda saqlanib qolgan (masalan, yuborish xatoga uchragani sababli
    hali Telegramga yetkazilmagan) fayllarni bittalab ro'yxatlab, sahifalarga
    bo'lib qaytaradi — har bir fayl o'z alohida qayta yuborish/o'chirish
    tugmasiga ega bo'ladi. Hali faol (yuklanayotgan) jobning fayllari to'liq
    bo'lmagani uchun ro'yxatga kiritilmaydi. Natija: [(text, keyboard), ...]."""
    manager = _manager(context)
    active_ids = {job.job_id for job in manager.jobs_for_chat(chat_id)}
    chat_dir = config.DOWNLOAD_DIR / str(chat_id)

    entries = []
    if chat_dir.exists():
        for folder in sorted(chat_dir.iterdir()):
            if not folder.is_dir() or folder.name in active_ids:
                continue
            for index, file_path in enumerate(find_downloaded_files(folder)):
                entries.append((folder.name, index, file_path))

    if not entries:
        return [("📁 No files saved on the server.", None)]

    chunks = [entries[i:i + _FILES_PER_PAGE] for i in range(0, len(entries), _FILES_PER_PAGE)]
    pages = []
    for page_num, chunk in enumerate(chunks, start=1):
        header = "📁 <b>Saved files:</b>"
        if len(chunks) > 1:
            header += f" ({page_num}/{len(chunks)})"
        lines = [header]
        buttons = []
        for job_id, index, file_path in chunk:
            size = file_path.stat().st_size
            lines.append(f"• {file_path.name} — {human_size(size)}")
            buttons.append([
                InlineKeyboardButton(f"📤 {file_path.name[:20]}", callback_data=f"resend:{job_id}:{index}"),
                InlineKeyboardButton("🗑", callback_data=f"delfile:{job_id}:{index}"),
            ])
        if page_num == len(chunks):
            buttons.append([
                InlineKeyboardButton("📤 Send all", callback_data="resend:all"),
                InlineKeyboardButton("🗑 Delete all", callback_data="delfile:all"),
            ])
        pages.append(("\n".join(lines), InlineKeyboardMarkup(buttons)))

    return pages


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for text, keyboard in _build_files_list_pages(context, chat_id):
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


def _scan_deletable_downloads(manager):
    """Faol bo'lmagan job papkalarini sanaydi: (papkalar soni, jami hajm baytda).
    Barcha chatlar bo'yicha, /clearall preview'i uchun."""
    active_ids = manager.all_job_ids()
    count = 0
    total_bytes = 0
    if config.DOWNLOAD_DIR.exists():
        for chat_folder in config.DOWNLOAD_DIR.iterdir():
            if not chat_folder.is_dir() or chat_folder.name == 'incoming':
                continue
            for job_folder in chat_folder.iterdir():
                if not job_folder.is_dir() or job_folder.name in active_ids:
                    continue
                count += 1
                for f in job_folder.rglob('*'):
                    if f.is_file():
                        try:
                            total_bytes += f.stat().st_size
                        except OSError:
                            pass
    return count, total_bytes


def _wipe_all_downloads(manager):
    """_scan_deletable_downloads aniqlagan hamma narsani o'chiradi — faol
    yuklashlar (istalgan chatdagi) tegilmaydi. 'incoming/' ham tozalanadi."""
    active_ids = manager.all_job_ids()
    if not config.DOWNLOAD_DIR.exists():
        return
    for chat_folder in config.DOWNLOAD_DIR.iterdir():
        if not chat_folder.is_dir():
            continue
        if chat_folder.name == 'incoming':
            shutil.rmtree(chat_folder, ignore_errors=True)
            chat_folder.mkdir(exist_ok=True)
            continue
        for job_folder in chat_folder.iterdir():
            if job_folder.is_dir() and job_folder.name not in active_ids:
                shutil.rmtree(job_folder, ignore_errors=True)
        try:
            chat_folder.rmdir()
        except OSError:
            pass


async def cleanup_stale_files(context: ContextTypes.DEFAULT_TYPE):
    """Vaqti-vaqti bilan (JobQueue orqali) ishga tushib, STALE_FILE_HOURS
    soatdan beri hech qanday fayli tegilmagan (yuborilmagan/o'chirilmagan)
    job papkalarini avtomatik o'chiradi va egasiga xabar beradi. Faol
    (hozir yuklanayotgan) joblarga tegilmaydi."""
    manager = context.application.bot_data['manager']
    active_ids = manager.all_job_ids()
    cutoff = time.time() - config.STALE_FILE_HOURS * 3600

    if not config.DOWNLOAD_DIR.exists():
        return

    for chat_folder in config.DOWNLOAD_DIR.iterdir():
        if not chat_folder.is_dir() or chat_folder.name == 'incoming':
            continue
        try:
            chat_id = int(chat_folder.name)
        except ValueError:
            continue

        removed_count = 0
        removed_bytes = 0
        for job_folder in chat_folder.iterdir():
            if not job_folder.is_dir() or job_folder.name in active_ids:
                continue
            files = [f for f in job_folder.rglob('*') if f.is_file()]
            if not files:
                shutil.rmtree(job_folder, ignore_errors=True)
                continue
            newest_mtime = max(f.stat().st_mtime for f in files)
            if newest_mtime > cutoff:
                continue
            for f in files:
                try:
                    removed_bytes += f.stat().st_size
                except OSError:
                    pass
            shutil.rmtree(job_folder, ignore_errors=True)
            removed_count += 1

        try:
            chat_folder.rmdir()
        except OSError:
            pass

        if removed_count:
            logger.info(
                "Auto-cleaned %d stale folder(s) (%s) for chat %s (older than %dh)",
                removed_count, human_size(removed_bytes), chat_id, config.STALE_FILE_HOURS,
            )
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🗑 {removed_count} file(s) ({human_size(removed_bytes)}) that were "
                        f"not sent/deleted for {config.STALE_FILE_HOURS} hours were "
                        "automatically removed from the server."
                    ),
                )
            except Exception:
                logger.exception("Failed to notify chat %s about stale cleanup", chat_id)


async def clearall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: barcha chatlarning saqlangan (faol bo'lmagan) fayllarini
    o'chirish uchun tasdiqlash so'raydi."""
    chat_id = update.effective_chat.id
    if chat_id not in config.ADMIN_CHAT_IDS:
        await update.message.reply_text("⛔ This command is for admins only.")
        return

    manager = _manager(context)
    count, total_bytes = _scan_deletable_downloads(manager)
    if count == 0:
        await update.message.reply_text("📁 Nothing to delete.")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚠️ Yes, delete EVERYTHING", callback_data="clearall:confirm"),
        InlineKeyboardButton("Cancel", callback_data="clearall:cancel"),
    ]])
    await update.message.reply_text(
        "⚠️ <b>Warning!</b> This will delete <b>ALL</b> users' files saved on "
        "the server (active downloads won't be affected).\n\n"
        f"📁 {count} folder(s), {human_size(total_bytes)} total.\n\n"
        "Are you sure you want to continue?",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def magnet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _start_job(update, context, update.message.text.strip(), is_magnet=True)


async def torrent_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    tg_file = await document.get_file()
    dest_dir = config.DOWNLOAD_DIR / 'incoming'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{update.effective_chat.id}_{document.file_unique_id}.torrent"
    await tg_file.download_to_drive(custom_path=str(dest_path))
    await _start_job(update, context, str(dest_path), is_magnet=False)


async def _start_job(update: Update, context: ContextTypes.DEFAULT_TYPE, source, is_magnet):
    manager = _manager(context)
    chat_id = update.effective_chat.id

    if manager.has_active_job(chat_id):
        await update.message.reply_text(
            "⏳ You already have an active download. Please wait for it to finish "
            "before sending a new one (or cancel it with the ⏹ Stop button)."
        )
        return

    try:
        job = manager.create_job(chat_id, source, is_magnet)
    except RuntimeError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return

    message = await update.message.reply_text(
        "🕒 Received, queued...", reply_markup=_keyboard(job.job_id)
    )
    job.message_id = message.message_id
    context.application.create_task(_process_job(context.bot, manager, job), update=update)


async def _ask_title_strip(bot, chat_id, sample_name):
    """Jobning birinchi fayl nomini yuborib, undan olib tashlanadigan qismni
    so'raydi. Javob (yoki /skip, yoki javobsiz kutish muddati) shu jobning
    barcha fayllariga qayta so'ramasdan qo'llanadi."""
    if chat_id in _pending_title_prompts:
        return None

    future = asyncio.get_event_loop().create_future()
    _pending_title_prompts[chat_id] = future
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "📄 File name:\n"
                f"<code>{sample_name}</code>\n\n"
                "Send the unwanted part to remove from the name "
                "(e.g.: <code>720p.HDTV.x264-HWE</code>).\n"
                "Send /skip to continue without changes."
            ),
            parse_mode=ParseMode.HTML,
        )
        try:
            return await asyncio.wait_for(future, timeout=config.TITLE_PROMPT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return None
    finally:
        _pending_title_prompts.pop(chat_id, None)


async def title_strip_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    future = _pending_title_prompts.get(update.effective_chat.id)
    if future and not future.done():
        future.set_result(update.message.text.strip())


async def title_strip_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    future = _pending_title_prompts.get(update.effective_chat.id)
    if future and not future.done():
        future.set_result(None)


async def _progress_ticker(bot, job):
    while not job.done:
        await asyncio.sleep(config.PROGRESS_EDIT_INTERVAL_SECONDS)
        if job.done or not job.status:
            continue
        text = format_progress(job.status)
        if text == job.last_message_text:
            continue
        job.last_message_text = text
        try:
            await bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.message_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=_keyboard(job.job_id),
            )
        except BadRequest as exc:
            if 'not modified' not in str(exc).lower():
                logger.warning("Failed to edit progress message for job %s: %s", job.job_id, exc)
        except TelegramError as exc:
            # Transient network hiccups etc. must never kill the ticker loop —
            # if they did, `await ticker` below would re-raise them and skip
            # delivery entirely even though the download itself succeeded.
            logger.warning("Failed to edit progress message for job %s: %s", job.job_id, exc)


async def _safe_edit_message(bot, chat_id, message_id, text, **kwargs):
    """edit_message_text'ni xato (masalan Telegramning flood-limiti —
    'Too many requests') butun yetkazib berish jarayonini to'xtatib
    qo'ymasligi uchun ushlab, faqat log yozadi."""
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, **kwargs)
    except TelegramError as exc:
        logger.warning("Failed to edit message %s in chat %s: %s", message_id, chat_id, exc)


async def _notify_safely(bot, chat_id, text):
    """Xabar yuborishda ham flood-limitga tegib qolsa avtomatik kutib qayta
    urinadi; oxir-oqibat baribir muvaffaqiyatsiz bo'lsa, faqat log yozadi —
    bu xabar (masalan xatolik haqida) yuqoridagi asosiy oqimni to'xtatib
    qo'ymasligi kerak."""
    async def attempt():
        await bot.send_message(chat_id=chat_id, text=text)
    try:
        await with_flood_retry(attempt)
    except TelegramError:
        logger.exception("Failed to notify chat %s", chat_id)


async def _process_job(bot, manager, job):
    try:
        async with manager.semaphore:
            try:
                await bot.edit_message_text(chat_id=job.chat_id, message_id=job.message_id, text="⏳ Starting...")
            except BadRequest:
                pass

            ticker = asyncio.create_task(_progress_ticker(bot, job))
            await asyncio.to_thread(run_job_sync, job)
            job.done = True
            try:
                await ticker
            except Exception:
                logger.exception("Progress ticker crashed for job %s", job.job_id)

            try:
                if job.stopped:
                    await _safe_edit_message(
                        bot, job.chat_id, job.message_id, "⏹ Download cancelled."
                    )
                elif job.error:
                    await _safe_edit_message(
                        bot, job.chat_id, job.message_id,
                        format_error(job.status.get('name', 'Torrent'), job.error),
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await _safe_edit_message(
                        bot, job.chat_id, job.message_id, format_done(job.status), parse_mode=ParseMode.HTML,
                    )
                    files = find_downloaded_files(job.save_path)
                    if not files:
                        raise RuntimeError("Downloaded files not found.")
                    title_strip = await _ask_title_strip(bot, job.chat_id, files[0].name)
                    for i, file_path in enumerate(files):
                        if i > 0:
                            await asyncio.sleep(INTER_FILE_DELAY_SECONDS)
                        await deliver_single_file(
                            bot, job.chat_id, job.message_id, file_path, title_strip=title_strip
                        )
                    if not config.KEEP_FILES_AFTER_SEND:
                        shutil.rmtree(job.save_path, ignore_errors=True)
                    await _notify_safely(
                        bot, job.chat_id, f"📦 {job.status.get('name', 'Torrent')} — all files sent."
                    )
            except Exception as exc:
                logger.exception("Failed to finalize job %s", job.job_id)
                await _notify_safely(bot, job.chat_id, f"❌ Error: {exc}")
    finally:
        # Nima bo'lishidan qat'iy nazar (hatto flood-limit tufayli xatolik
        # xabari ham yuborilmasa) — job doim "faol"lar ro'yxatidan chiqarilishi
        # kerak, aks holda uning fayllari /files'da abadiy ko'rinmay qoladi.
        manager.remove_job(job.job_id)


async def _refresh_files_list_message(query, context, chat_id):
    pages = _build_files_list_pages(context, chat_id)
    text, keyboard = pages[0]
    if len(pages) > 1:
        text += f"\n\n… {len(pages) - 1} more page(s). Send /files for the full list."
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except BadRequest as exc:
        if 'not modified' not in str(exc).lower():
            raise


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, _, payload = query.data.partition(':')

    if action == 'clearall':
        chat_id = query.message.chat_id
        if chat_id not in config.ADMIN_CHAT_IDS:
            await query.answer("⛔ No permission.", show_alert=True)
            return
        if payload == 'cancel':
            await query.answer("Cancelled.")
            await query.edit_message_text("Cancelled.")
            return
        manager = _manager(context)
        count, total_bytes = _scan_deletable_downloads(manager)
        _wipe_all_downloads(manager)
        await query.answer("Everything deleted.")
        await query.edit_message_text(f"✅ {count} folder(s) deleted, {human_size(total_bytes)} freed.")
        return

    if action == 'delfile':
        chat_id = query.message.chat_id
        chat_dir = config.DOWNLOAD_DIR / str(chat_id)

        if payload == 'all':
            manager = _manager(context)
            active_ids = {job.job_id for job in manager.jobs_for_chat(chat_id)}
            if chat_dir.exists():
                for folder in chat_dir.iterdir():
                    if folder.is_dir() and folder.name not in active_ids:
                        shutil.rmtree(folder, ignore_errors=True)
            await query.answer("Everything deleted.")
        else:
            job_id, _, index_str = payload.partition(':')
            file_path = _resolve_file(chat_dir, job_id, index_str)
            if file_path is None:
                await query.answer("File not found.", show_alert=True)
            else:
                file_path.unlink(missing_ok=True)
                try:
                    file_path.parent.rmdir()
                except OSError:
                    pass
                await query.answer("Deleted.")

        await _refresh_files_list_message(query, context, chat_id)
        return

    if action == 'resend':
        chat_id = query.message.chat_id
        chat_dir = config.DOWNLOAD_DIR / str(chat_id)

        if payload == 'all':
            manager = _manager(context)
            active_ids = {job.job_id for job in manager.jobs_for_chat(chat_id)}
            all_files = []
            if chat_dir.exists():
                for folder in sorted(chat_dir.iterdir()):
                    if folder.is_dir() and folder.name not in active_ids:
                        all_files.extend(find_downloaded_files(folder))

            await query.answer("Sending all files...")
            title_strip = await _ask_title_strip(context.bot, chat_id, all_files[0].name) if all_files else None
            for i, file_path in enumerate(all_files):
                if i > 0:
                    await asyncio.sleep(INTER_FILE_DELAY_SECONDS)
                await deliver_single_file(
                    context.bot, chat_id, query.message.message_id, file_path, title_strip=title_strip
                )
            if all_files:
                await _notify_safely(context.bot, chat_id, f"📦 {len(all_files)} file(s) sent.")
        else:
            job_id, _, index_str = payload.partition(':')
            file_path = _resolve_file(chat_dir, job_id, index_str)
            if file_path is None:
                await query.answer("File not found.", show_alert=True)
                return
            await query.answer("Sending file...")
            title_strip = await _ask_title_strip(context.bot, chat_id, file_path.name)
            await deliver_single_file(
                context.bot, chat_id, query.message.message_id, file_path, title_strip=title_strip
            )

        await _refresh_files_list_message(query, context, chat_id)
        return

    job_id = payload
    manager = _manager(context)
    job = manager.get_job(job_id)

    if job is None or job.chat_id != query.message.chat_id:
        await query.answer("This download was not found or has already finished.", show_alert=True)
        return

    if job.torrent_downloader is None:
        await query.answer("Not started yet, please wait...", show_alert=True)
        return

    if action == 'pause':
        job.torrent_downloader.pause_download()
        job.paused = True
        await query.answer("Paused.")
    elif action == 'resume':
        job.torrent_downloader.resume_download()
        job.paused = False
        await query.answer("Resumed.")
    elif action == 'stop':
        job.cancel_requested = True
        await query.answer("Stopping...")
    else:
        await query.answer()
