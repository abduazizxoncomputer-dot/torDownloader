"""
Bir martalik interaktiv skript: userbot (shaxsiy Telegram akkount) sessiyasini yaratadi.

Bu skriptni SIZ o'zingiz, o'z terminalingizda ishga tushirishingiz kerak — u
telefon raqamingiz, Telegramdan keladigan tasdiqlash kodi va (agar yoqilgan
bo'lsa) ikki bosqichli parolni so'raydi. Bular faqat sizga tegishli va hech
qayerga saqlanmaydi — faqat mahalliy sessiya fayli (sessions/*.session)
yaratiladi, u orqali keyinchalik bot katta fayllarni yubora oladi.

Ishga tushirish:
    python scripts/create_userbot_session.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyrogram import Client

from telegram_bot import config


def main():
    if not config.API_ID or not config.API_HASH:
        print("Xatolik: .env faylida API_ID va API_HASH to'ldirilmagan.")
        print("my.telegram.org dan olib, .env fayliga qo'shing, so'ng qayta ishga tushiring.")
        raise SystemExit(1)

    app = Client(
        name=config.USERBOT_SESSION_NAME,
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        workdir=str(config.SESSION_DIR),
    )

    with app:
        me = app.get_me()
        print(f"\nMuvaffaqiyatli login qilindi: {me.first_name} (@{me.username or me.id})")
        print(f"Sessiya saqlandi: {config.SESSION_DIR / (config.USERBOT_SESSION_NAME + '.session')}")
        print("\nEndi 'python scripts/setup_storage_channel.py' ni ishga tushiring.")


if __name__ == '__main__':
    main()
