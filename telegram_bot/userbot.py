import logging
from pathlib import Path
from typing import Optional

from pyrogram import Client
from telegram.constants import ParseMode

from telegram_bot import config

logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def is_enabled():
    return config.USERBOT_ENABLED


async def start():
    global _client
    if not config.USERBOT_ENABLED:
        logger.warning(
            "Userbot relay o'chirilgan (API_ID/API_HASH/STORAGE_CHAT_ID to'liq emas) — "
            "%dMB dan katta fayllar avtomatik qismlarga bo'linadi.",
            config.BOT_UPLOAD_LIMIT_MB,
        )
        return

    _client = Client(
        name=config.USERBOT_SESSION_NAME,
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        workdir=str(config.SESSION_DIR),
    )
    await _client.start()
    logger.info("Userbot relay ishga tushdi.")


async def stop():
    if _client is not None:
        await _client.stop()
        logger.info("Userbot relay to'xtatildi.")


async def relay_large_file(bot, chat_id, path: Path, caption=None, progress=None):
    """`path`ni userbot orqali storage chatga yuklaydi, so'ng bot uni
    (qayta yuklamasdan, copy_message orqali) `chat_id`ga yuboradi — shu
    sababli Bot API'ning yuklash hajmi chegarasi bu yerga tegishli emas.

    `progress`, agar berilgan bo'lsa, Pyrogram konvensiyasiga ko'ra
    `(current_bytes, total_bytes)` bilan real vaqtda chaqiriladi."""
    if _client is None:
        raise RuntimeError("Userbot relay ishga tushirilmagan.")

    storage_message = await _client.send_document(
        config.STORAGE_CHAT_ID,
        document=str(path),
        file_name=path.name,
        progress=progress,
    )
    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=config.STORAGE_CHAT_ID,
            message_id=storage_message.id,
            caption=caption,
            parse_mode=ParseMode.HTML if caption else None,
        )
    finally:
        await _client.delete_messages(config.STORAGE_CHAT_ID, storage_message.id)
