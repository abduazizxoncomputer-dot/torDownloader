import asyncio
from pathlib import Path

from torrentp import TorrentDownloader


TORRENT_LINK = (
    "https://releases.ubuntu.com/24.04.4/"
    "ubuntu-24.04.4-desktop-amd64.iso.torrent"
)
SAVE_PATH = Path("./downloads").expanduser().resolve()
PORT = 6881
LOW_MEMORY = True
KEEP_SEEDING = False


async def main():
    SAVE_PATH.mkdir(parents=True, exist_ok=True)

    downloader = TorrentDownloader(
        TORRENT_LINK,
        save_path=str(SAVE_PATH),
        port=PORT,
        stop_after_download=not KEEP_SEEDING,
        low_memory=LOW_MEMORY,
    )

    print(f"Downloading: {TORRENT_LINK}")
    print(f"Saving into: {SAVE_PATH}")
    print(f"low_memory={LOW_MEMORY} keep_seeding={KEEP_SEEDING}")

    try:
        await downloader.start_download()
    except KeyboardInterrupt:
        print("Interrupted, stopping torrent session...")
        downloader.stop_download()
        raise SystemExit(130)


if __name__ == "__main__":
    asyncio.run(main())
