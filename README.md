# TorrentP

##  Wrapped python library for downloading from torrent

[![Torrentp](https://github.com/iw4p/torrentp/raw/master/images/tintin.jpeg
)](https://pypi.org/project/torrentp/)

### Download from torrent with .torrent file or magnet link. With just 3 lines of python code.

[![PyPI version](https://img.shields.io/pypi/v/TorrentP.svg)](https://pypi.org/project/TorrentP)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/TorrentP.svg)](#Installation)
[![Downloads](https://pepy.tech/badge/TorrentP)](https://pepy.tech/project/TorrentP)

### Installation

```sh
$ pip install torrentp
```
Also can be found on [pypi](https://pypi.org/project/torrentp/)

### How can I use it?
  - Install the package by pip package manager.
  - After installing, you can use it and call the library.
  - You have to pass magnet link or torrent file, and a path for saving the file. use . (dot) for saving in current directory.

Download with magnet link:
```python
import asyncio
from torrentp import TorrentDownloader
torrent_file = TorrentDownloader("magnet:...", '.')
# Start the download process
asyncio.run(torrent_file.start_download()) # start_download() is a asynchronous method 

# Pausing the download
torrent_file.pause_download()

# Resuming the download
torrent_file.resume_download()

# Stopping the download
torrent_file.stop_download()
```
Or download with .torrent file:
```python
import asyncio
from torrentp import TorrentDownloader
torrent_file = TorrentDownloader("test.torrent", '.')
# Start the download process
asyncio.run(torrent_file.start_download()) # start_download() is a asynchronous method 

# Pausing the download
torrent_file.pause_download()

# Resuming the download
torrent_file.resume_download()

# Stopping the download
torrent_file.stop_download()
```
#### How can I use a custom port?

```python
torrent_file = TorrentDownloader("magnet/torrent.file", '.', port=0000)
```
#### How can I reduce memory usage for large torrents?

```python
torrent_file = TorrentDownloader("magnet/torrent.file", '.', low_memory=True)
```

This applies libtorrent's low-memory session profile. It can reduce RAM usage, but may also reduce download performance.

#### How can I limit the upload or download speed?

Download Using 0 (default number) means unlimited speed:
```python
await torrent_file.start_download(download_speed=0, upload_speed=0)
```
Or download with specifc number (kB/s):
```python
await torrent_file.start_download(download_speed=2, upload_speed=1)
```
### Using Command Line Interface (CLI)
Download with a magnet link:
```sh
$ torrentp --link 'magnet:...'
```

or download with .torrent file:
```sh
$ torrentp --link 'test.torrent'
```
#### You can also use ```--help``` parameter to display all the parameters that you can use

| args | help | type |
| ------ | ------ | ------ |
| --link | Torrent link. Example: [--link 'file.torrent'] or [--link 'magnet:...']  [required] | ```str``` |
| --download_speed | Download speed with a specific number (kB/s). Default: 0, means unlimited speed | ```int``` |
| --upload_speed | Upload speed with a specific number (kB/s). Default: 0, means unlimited speed | ```int``` |
| --save_path | Path to save the file, default: '.' | ```str``` |
| --stop_after_download | Stop the download immediately after completion without seeding | ```flag``` |
| --help |Show this message and exit |  |

Example with all commands:
```sh
$ torrentp --link 'magnet:...' --download_speed 100 --upload_speed 50 --save_path '.' --stop_after_download
```

### Telegram bot

This repo also includes a Telegram bot (`telegram_bot/`) built on top of the `torrentp` library: send it a magnet link or a `.torrent` file and it downloads the torrent on the server, then sends the resulting file(s) back to you in the chat, with live progress and pause/resume/stop buttons. Multiple downloads run in parallel.

1. Install dependencies:
   ```sh
   pip install -r requirements-bot.txt
   pip install -e .
   ```
2. Copy `.env.example` to `.env` and set `BOT_TOKEN` (get one from [@BotFather](https://t.me/BotFather)).
3. Run the bot:
   ```sh
   python -m telegram_bot.main
   ```

#### Sending files larger than 50MB

The public Telegram Bot API caps a bot's uploads at 50MB per file. This repo raises that via a **userbot relay** (no Docker needed): a second Telegram session, logged in with your own phone number through [Pyrogram](https://docs.pyrogram.org), uploads the large file into a private "storage" channel; the bot then `copy_message`s it into the user's chat. Since that's a server-side copy rather than a fresh upload, the Bot API's 50MB cap doesn't apply — files up to Telegram's absolute ~2000MB per-file limit go through.

Setup (one-time):
1. Get `API_ID` / `API_HASH` from [my.telegram.org](https://my.telegram.org) and put them in `.env`.
2. Run `python scripts/create_userbot_session.py` — this is interactive (asks for your phone number, the login code Telegram sends you, and your 2FA password if you have one) and must be run by you in your own terminal. It saves a session file under `sessions/`.
3. Run `python scripts/setup_storage_channel.py` — non-interactive; it creates a private storage channel, adds the bot to it as admin, and writes `STORAGE_CHAT_ID` into `.env` for you.
4. Restart the bot.

An alternative (without a userbot, but requiring Docker) is a [Local Bot API Server](https://github.com/tdlib/telegram-bot-api) — point the bot at it via `LOCAL_BOT_API_BASE_URL` / `LOCAL_BOT_API_BASE_FILE_URL` in `.env`. Only one of the two is needed; the userbot relay takes priority if both are configured.

~2000MB is Telegram's hard per-file limit regardless of method — there is no way around it. Files larger than the active limit are automatically split into sequential parts (`file.ext.part001`, `file.ext.part002`, ...) and sent one after another; the last part's caption includes the `copy /b` (Windows) / `cat` (Linux/macOS) command to reassemble them.

### Manual integration test

You can run a manual download test against the Ubuntu 24.04.4 desktop ISO torrent:

```sh
python3 scripts/test_download_ubuntu.py
```

Edit the constants at the top of the script to change the torrent URL, save path, port, or `LOW_MEMORY` setting.

### To do list
- [x] Limit upload and download speed
- [x] User can change the port
- [x] CLI
- [x] Pause / Resume / Stop

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=iw4p/torrentp&type=Date)](https://star-history.com/#iw4p/torrentp&Date)

### Issues
Feel free to submit issues and enhancement requests or contact me via [vida.page/nima](https://vida.page/nima).

### Contributing
Please refer to each project's style and contribution guidelines for submitting patches and additions. In general, we follow the "fork-and-pull" Git workflow.

 1. **Fork** the repo on GitHub
 2. **Clone** the project to your own machine
 3. **Update the Version** inside __init__.py
 4. **Commit** changes to your own branch
 5. **Push** your work back up to your fork
 6. Submit a **Pull request** so that we can review your changes
