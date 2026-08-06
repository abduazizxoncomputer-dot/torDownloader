import asyncio
import logging

from torrentp import TorrentDownloader

from telegram_bot import config
from telegram_bot.jobs import Job, JobCancelled

logger = logging.getLogger(__name__)


def run_job_sync(job: Job):
    """Runs a single torrent download to completion. Executed in a worker
    thread via asyncio.to_thread so that a blocking torrent job never stalls
    the bot's event loop or other concurrent downloads."""
    torrent_downloader = TorrentDownloader(
        job.source,
        job.save_path,
        port=job.port,
        stop_after_download=config.STOP_AFTER_DOWNLOAD,
    )
    job.torrent_downloader = torrent_downloader

    try:
        asyncio.run(torrent_downloader.start_download(progress_callback=job.update_status))
    except JobCancelled:
        try:
            torrent_downloader.stop_download()
        except Exception:
            logger.exception("Error while stopping cancelled job %s", job.job_id)
        job.stopped = True
    except Exception as exc:
        logger.exception("Job %s failed", job.job_id)
        job.error = str(exc)
    finally:
        job.done = True
