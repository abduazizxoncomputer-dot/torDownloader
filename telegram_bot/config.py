import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int(name, default):
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)   


BOT_TOKEN = os.getenv('BOT_TOKEN', '')  

DOWNLOAD_DIR = Path(os.getenv('DOWNLOAD_DIR', './downloads')).resolve()
SESSION_DIR = Path(os.getenv('SESSION_DIR', './sessions')).resolve()

BASE_PORT = _env_int('BASE_PORT', 6881)
PORT_POOL_SIZE = _env_int('PORT_POOL_SIZE', 500)

# Global concurrent-download cap. Real fairness is enforced per-user instead
# (one active download per chat, see DownloadManager.has_active_job) so this
# is set high enough to not be the practical bottleneck.
MAX_CONCURRENT_DOWNLOADS = _env_int('MAX_CONCURRENT_DOWNLOADS', 500)

STOP_AFTER_DOWNLOAD = _env_bool('STOP_AFTER_DOWNLOAD', True)
KEEP_FILES_AFTER_SEND = _env_bool('KEEP_FILES_AFTER_SEND', False)

LOCAL_BOT_API_BASE_URL = os.getenv('LOCAL_BOT_API_BASE_URL', '').strip() or None
LOCAL_BOT_API_BASE_FILE_URL = os.getenv('LOCAL_BOT_API_BASE_FILE_URL', '').strip() or None

# --- Userbot relay (Pyrogram) for files above the plain Bot API limit ---
# Obtained from my.telegram.org. Required only for the userbot relay path.
API_ID = _env_int('API_ID', 0) or None
API_HASH = os.getenv('API_HASH', '').strip() or None
USERBOT_SESSION_NAME = os.getenv('USERBOT_SESSION_NAME', 'telegram_bot_userbot')
# Private channel/group id the userbot uploads to and the bot copies from.
# Both the userbot account and the bot must be members of this chat.
STORAGE_CHAT_ID = _env_int('STORAGE_CHAT_ID', 0) or None

USERBOT_ENABLED = bool(API_ID and API_HASH and STORAGE_CHAT_ID)

# Plain Bot API upload cap. A Local Bot API Server lets the bot's own token
# push files up to ~1900MB directly, with no userbot relay needed — so raise
# this cap to match whenever one is configured.
_DEFAULT_BOT_UPLOAD_LIMIT_MB = 1900 if LOCAL_BOT_API_BASE_URL else 45
BOT_UPLOAD_LIMIT_MB = _env_int('BOT_UPLOAD_LIMIT_MB', _DEFAULT_BOT_UPLOAD_LIMIT_MB)
BOT_UPLOAD_LIMIT_BYTES = BOT_UPLOAD_LIMIT_MB * 1024 * 1024

# Files above this are sent via the userbot relay instead of a direct bot upload.
USERBOT_UPLOAD_LIMIT_MB = _env_int('USERBOT_UPLOAD_LIMIT_MB', 1900)
USERBOT_UPLOAD_LIMIT_BYTES = USERBOT_UPLOAD_LIMIT_MB * 1024 * 1024

# Telegram hard-caps a single file at ~2000MB regardless of upload method
# (Local Bot API Server or userbot). Anything larger is split into parts.
_DEFAULT_CHUNK_MB = 1900 if (LOCAL_BOT_API_BASE_URL or USERBOT_ENABLED) else 45
CHUNK_SIZE_MB = _env_int('CHUNK_SIZE_MB', _DEFAULT_CHUNK_MB)
CHUNK_SIZE_BYTES = CHUNK_SIZE_MB * 1024 * 1024

PROGRESS_EDIT_INTERVAL_SECONDS = _env_int('PROGRESS_EDIT_INTERVAL_SECONDS', 4)

# Link shown as "ORDERED MOVIES" in the caption attached to every delivered file.
ORDER_CHANNEL_URL = os.getenv('ORDER_CHANNEL_URL', 'https://t.me/Cart_In_Eng').strip()

# Yuklab olish tugagach, foydalanuvchidan sarlavhadan olib tashlanadigan qismni
# so'raganda, javob kutiladigan maksimal vaqt. Shu vaqt ichida javob kelmasa,
# avtomatik (regex asosidagi) nom tozalashga qaytiladi.
TITLE_PROMPT_TIMEOUT_SECONDS = _env_int('TITLE_PROMPT_TIMEOUT_SECONDS', 180)

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)
