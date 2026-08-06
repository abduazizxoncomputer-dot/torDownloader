import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from telegram_bot import config
from telegram_bot.file_delivery import deliver_job_files
from telegram_bot.jobs import DownloadManager
from telegram_bot.progress import format_done, format_error, format_progress
from telegram_bot.runner import run_job_sync

logger = logging.getLogger(__name__)

WELCOME = (
    "Salom! Men torrent yuklab beruvchi botman.\n\n"
    "Menga magnet link yoki .torrent fayl yuboring — men uni serverga yuklab, "
    "sizga qaytarib beraman (katta fayllar avtomatik qismlarga bo'linadi).\n\n"
    "/status — aktiv yuklashlar ro'yxati"
)


def _manager(context: ContextTypes.DEFAULT_TYPE) -> DownloadManager:
    return context.application.bot_data['manager']


def _keyboard(job_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⏸ Pauza", callback_data=f"pause:{job_id}"),
        InlineKeyboardButton("▶️ Davom", callback_data=f"resume:{job_id}"),
        InlineKeyboardButton("⏹ To'xtatish", callback_data=f"stop:{job_id}"),
    ]])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = _manager(context)
    jobs = manager.jobs_for_chat(update.effective_chat.id)
    if not jobs:
        await update.message.reply_text("Aktiv yuklashlar yo'q.")
        return

    lines = []
    for job in jobs:
        name = job.status.get('name') or job.source[:40]
        total = job.status.get('total_wanted') or 0
        done = job.status.get('total_done') or 0
        percent = (done / total * 100) if total else 0.0
        lines.append(f"• {name} — {percent:.1f}%")
    await update.message.reply_text("\n".join(lines))


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
            "⏳ Sizda allaqachon faol yuklash bor. Yangisini yuborishdan oldin uning "
            "tugashini kuting (yoki ⏹ To'xtatish tugmasi bilan bekor qiling)."
        )
        return

    try:
        job = manager.create_job(chat_id, source, is_magnet)
    except RuntimeError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return

    message = await update.message.reply_text(
        "🕒 Qabul qilindi, navbatda...", reply_markup=_keyboard(job.job_id)
    )
    job.message_id = message.message_id
    context.application.create_task(_process_job(context.bot, manager, job), update=update)


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


async def _process_job(bot, manager, job):
    async with manager.semaphore:
        try:
            await bot.edit_message_text(chat_id=job.chat_id, message_id=job.message_id, text="⏳ Boshlanmoqda...")
        except BadRequest:
            pass

        ticker = asyncio.create_task(_progress_ticker(bot, job))
        await asyncio.to_thread(run_job_sync, job)
        job.done = True
        await ticker

        try:
            if job.stopped:
                await bot.edit_message_text(
                    chat_id=job.chat_id, message_id=job.message_id, text="⏹ Yuklab olish bekor qilindi."
                )
            elif job.error:
                await bot.edit_message_text(
                    chat_id=job.chat_id,
                    message_id=job.message_id,
                    text=format_error(job.status.get('name', 'Torrent'), job.error),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await bot.edit_message_text(
                    chat_id=job.chat_id,
                    message_id=job.message_id,
                    text=format_done(job.status),
                    parse_mode=ParseMode.HTML,
                )
                await deliver_job_files(bot, job.chat_id, job.message_id, job.save_path)
                await bot.send_message(
                    chat_id=job.chat_id,
                    text=f"📦 {job.status.get('name', 'Torrent')} — barcha fayllar yuborildi.",
                )
        except Exception as exc:
            logger.exception("Failed to finalize job %s", job.job_id)
            await bot.send_message(chat_id=job.chat_id, text=f"❌ Xatolik: {exc}")

    manager.remove_job(job.job_id)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, _, job_id = query.data.partition(':')
    manager = _manager(context)
    job = manager.get_job(job_id)

    if job is None or job.chat_id != query.message.chat_id:
        await query.answer("Bu yuklash topilmadi yoki allaqachon tugagan.", show_alert=True)
        return

    if job.torrent_downloader is None:
        await query.answer("Hali boshlanmagan, kuting...", show_alert=True)
        return

    if action == 'pause':
        job.torrent_downloader.pause_download()
        job.paused = True
        await query.answer("Pauza qilindi.")
    elif action == 'resume':
        job.torrent_downloader.resume_download()
        job.paused = False
        await query.answer("Davom ettirildi.")
    elif action == 'stop':
        job.cancel_requested = True
        await query.answer("To'xtatilmoqda...")
    else:
        await query.answer()
