import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

from telegram_bot import config


class JobCancelled(Exception):
    """Raised from within the progress callback to unwind an in-progress download."""


@dataclass
class Job:
    job_id: str
    chat_id: int
    source: str
    is_magnet: bool
    save_path: str
    port: int
    message_id: Optional[int] = None
    torrent_downloader: object = None
    status: dict = field(default_factory=dict)
    done: bool = False
    paused: bool = False
    stopped: bool = False
    cancel_requested: bool = False
    error: Optional[str] = None
    last_message_text: Optional[str] = None

    def update_status(self, status_dict):
        if self.cancel_requested:
            raise JobCancelled(self.job_id)
        self.status = status_dict


class DownloadManager:
    def __init__(self):
        pool_size = max(config.PORT_POOL_SIZE, config.MAX_CONCURRENT_DOWNLOADS)
        self._free_ports = list(range(config.BASE_PORT, config.BASE_PORT + pool_size))
        self._jobs: dict[str, Job] = {}
        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)

    def allocate_port(self):
        if not self._free_ports:
            raise RuntimeError("No free ports available for a new torrent session.")
        return self._free_ports.pop()

    def release_port(self, port):
        if port not in self._free_ports:
            self._free_ports.append(port)

    def create_job(self, chat_id, source, is_magnet):
        job_id = uuid.uuid4().hex[:8]
        save_path = config.DOWNLOAD_DIR / str(chat_id) / job_id
        save_path.mkdir(parents=True, exist_ok=True)
        port = self.allocate_port()
        job = Job(
            job_id=job_id,
            chat_id=chat_id,
            source=source,
            is_magnet=is_magnet,
            save_path=str(save_path),
            port=port,
        )
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id):
        return self._jobs.get(job_id)

    def remove_job(self, job_id):
        job = self._jobs.pop(job_id, None)
        if job is not None:
            self.release_port(job.port)
        return job

    def jobs_for_chat(self, chat_id):
        return [job for job in self._jobs.values() if job.chat_id == chat_id]

    def all_job_ids(self):
        return set(self._jobs.keys())

    def has_active_job(self, chat_id):
        return any(not job.done for job in self.jobs_for_chat(chat_id))
