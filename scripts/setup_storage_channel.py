"""
Userbot sessiyasi tayyor bo'lgach ishga tushiriladigan sozlash skripti (interaktiv emas).

Nima qiladi:
  1. Maxfiy "storage" kanal yaratadi (userbot nomidan)
  2. Botni o'sha kanalga admin sifatida qo'shadi
  3. STORAGE_CHAT_ID ni .env fayliga yozadi

Talab: avval 'python scripts/create_userbot_session.py' bajarilgan bo'lishi kerak.

Ishga tushirish:
    python scripts/setup_storage_channel.py
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import set_key
from pyrogram import Client
from pyrogram.types import ChatPrivileges

from telegram_bot import config

ENV_PATH = Path(__file__).resolve().parent.parent / '.env'


def get_bot_username():
    # Plain synchronous HTTP call (rather than python-telegram-bot's async
    # client) so we don't touch asyncio's event loop before Pyrogram's
    # Client does its own synchronous asyncio.get_event_loop() setup below.
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getMe"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    if not payload.get('ok'):
        raise RuntimeError(f"getMe failed: {payload}")
    return payload['result']['username']


def main():
    if not config.API_ID or not config.API_HASH:
        print("Xatolik: .env faylida API_ID va API_HASH to'ldirilmagan.")
        raise SystemExit(1)

    if not config.BOT_TOKEN:
        print("Xatolik: .env faylida BOT_TOKEN to'ldirilmagan.")
        raise SystemExit(1)

    session_file = config.SESSION_DIR / f"{config.USERBOT_SESSION_NAME}.session"
    if not session_file.exists():
        print("Xatolik: userbot sessiyasi topilmadi. Avval quyidagini ishga tushiring:")
        print("  python scripts/create_userbot_session.py")
        raise SystemExit(1)

    bot_username = get_bot_username()
    print(f"Bot: @{bot_username}")

    app = Client(
        name=config.USERBOT_SESSION_NAME,
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        workdir=str(config.SESSION_DIR),
    )

    with app:
        chat = app.create_channel(
            title="TorrentBot Storage",
            description="Bot uchun katta fayllarni vaqtinchalik saqlash kanali (avtomatik yaratilgan).",
        )
        print(f"Kanal yaratildi: {chat.title} (id={chat.id})")

        # Bots can't be invited as a plain member first (Telegram rejects that
        # for channels) — promoting directly both invites and grants admin
        # rights in a single call, same as the "Add Admin" flow in the app.
        app.promote_chat_member(
            chat.id,
            bot_username,
            privileges=ChatPrivileges(
                can_post_messages=True,
                can_edit_messages=True,
                can_delete_messages=True,
            ),
        )
        print(f"@{bot_username} kanalga admin sifatida qo'shildi.")

    set_key(str(ENV_PATH), 'STORAGE_CHAT_ID', str(chat.id))
    print(f"\nSTORAGE_CHAT_ID={chat.id} .env fayliga yozildi.")
    print("Botni qayta ishga tushiring — endi katta fayllar userbot orqali yuboriladi.")


if __name__ == '__main__':
    main()
