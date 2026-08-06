import logging

from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from telegram_bot import config, handlers, userbot
from telegram_bot.jobs import DownloadManager

logger = logging.getLogger(__name__)


async def _on_startup(application: Application):
    await userbot.start()


async def _on_shutdown(application: Application):
    await userbot.stop()


def build_application():
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi. .env faylida BOT_TOKEN ni belgilang.")

    builder = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .read_timeout(600)
        .write_timeout(600)
        .connect_timeout(60)
        .pool_timeout(60)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
    )

    if config.LOCAL_BOT_API_BASE_URL:
        builder = builder.base_url(config.LOCAL_BOT_API_BASE_URL).local_mode(True)
        if config.LOCAL_BOT_API_BASE_FILE_URL:
            builder = builder.base_file_url(config.LOCAL_BOT_API_BASE_FILE_URL)
        logger.info("Using Local Bot API Server at %s", config.LOCAL_BOT_API_BASE_URL)

    if config.USERBOT_ENABLED:
        logger.info("Userbot relay yoqilgan (storage chat: %s).", config.STORAGE_CHAT_ID)
    elif not config.LOCAL_BOT_API_BASE_URL:
        logger.warning(
            "Userbot relay ham, Local Bot API Server ham sozlanmagan — fayl yuborish %dMB bilan "
            "cheklanadi (kattaroq fayllar avtomatik qismlarga bo'linadi).",
            config.BOT_UPLOAD_LIMIT_MB,
        )

    application = builder.build()
    application.bot_data['manager'] = DownloadManager()

    application.add_handler(CommandHandler('start', handlers.start_command))
    application.add_handler(CommandHandler('help', handlers.help_command))
    application.add_handler(CommandHandler('status', handlers.status_command))
    application.add_handler(MessageHandler(filters.Regex(r'(?i)^magnet:'), handlers.magnet_handler))
    application.add_handler(MessageHandler(filters.Document.FileExtension('torrent'), handlers.torrent_file_handler))
    application.add_handler(CallbackQueryHandler(handlers.button_callback))

    return application


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    application = build_application()
    application.run_polling(allowed_updates=['message', 'callback_query'])


if __name__ == '__main__':
    main()
