import asyncio
import logging
import time

from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

logger = logging.getLogger(__name__)


class Downloader:
    def __init__(self, session, torrent_info, save_path, libtorrent, is_magnet, stop_after_download=False):
        self._session = session
        self._torrent_info = torrent_info
        self._save_path = save_path
        self._file = None
        self._status = None
        self._name = ''
        self._state = ''
        self._lt = libtorrent
        self._add_torrent_params = None
        self._is_magnet = is_magnet
        self._paused = False
        self._stop_after_download = stop_after_download

    def _get_sparse_storage_mode(self):
        if self._lt is None:
            return None

        storage_mode = getattr(self._lt, 'storage_mode_t', None)
        if storage_mode is not None and hasattr(storage_mode, 'storage_mode_sparse'):
            return storage_mode.storage_mode_sparse

        return getattr(self._lt, 'storage_mode_sparse', None)

    def _build_add_torrent_params(self):
        params = {'save_path': f'{self._save_path}'}
        sparse_mode = self._get_sparse_storage_mode()
        if sparse_mode is not None:
            params['storage_mode'] = sparse_mode

        if self._is_magnet:
            self._add_torrent_params = self._torrent_info
            self._add_torrent_params.save_path = self._save_path
            try:
                if sparse_mode is not None:
                    self._add_torrent_params.storage_mode = sparse_mode
            except Exception:
                pass
            return self._add_torrent_params

        params['ti'] = self._torrent_info
        return params

    def status(self, progress_callback=None):
        if self._file is None:
            if not self._is_magnet:
                self._file = self._session.add_torrent(self._build_add_torrent_params())
                logger.info(f"Torrent {self._file.status().name} added.")
            else:
                self._file = self._session.add_torrent(self._build_add_torrent_params())
                logger.info("Fetching magnet metadata...")
                while not self._file.has_metadata():
                    if progress_callback is not None:
                        progress_callback(self._status_dict(self._file.status(), state_override='fetching_metadata'))
                    time.sleep(1)
                logger.info("Metadata fetched successfully.")

        self._status = self._file.status()
        return self._status

    @property
    def name(self):
        self._name = self.status().name
        return self._name

    @staticmethod
    def _status_dict(status, state_override=None):
        return {
            'name': status.name,
            'total_wanted': status.total_wanted,
            'total_done': status.total_done,
            'num_peers': status.num_peers,
            'state': state_override or str(status.state),
            'is_seeding': status.is_seeding,
            'download_rate': status.download_rate,
            'upload_rate': status.upload_rate,
        }

    async def download(self, progress_callback=None):
        if progress_callback is not None:
            status = self.status(progress_callback=progress_callback)
            while not status.is_seeding:
                if not self._paused:
                    status = self.status(progress_callback=progress_callback)
                    progress_callback(self._status_dict(status))

                await asyncio.sleep(1)

            progress_callback(self._status_dict(status))
            logger.info(f"Download of {status.name} completed.")
            if self._stop_after_download:
                self.stop()
            return

        pbar = Progress(
            TextColumn("[bold blue]{task.description}", justify="right"),
            BarColumn(),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            # TextColumn("[orange1]{task.fields[peers]} peers"), # Number of peers
            # TextColumn("[purple]{task.fields[status]}"), # current status
            TimeRemainingColumn(compact=True, elapsed_when_finished=True),
        )

        with pbar:
            status = self.status()
            task_id = pbar.add_task(f"{status.name}", total=status.total_wanted, peers=0, status=status.state)

            while not status.is_seeding:
                if not self._paused:
                    status = self.status()
                    pbar.update(task_id, completed=status.total_done, total=status.total_wanted, peers=status.num_peers, status=status.state)

                await asyncio.sleep(1)

        logger.info(f"Download of {status.name} completed.")
        if self._stop_after_download:
            self.stop()

    def pause(self):
        if self._file:
            self._file.pause()
            self._paused = True
            logger.info("Download paused successfully.")
        else:
            logger.error("Download file instance not found.")

    def resume(self):
        if self._file:
            if self._paused:
                self._file.resume()
                self._paused = False
                logger.info("Download resumed successfully.")
            else:
                logger.warning("Download is not paused. No action taken.")
        else:
            logger.error("Download file instance not found.")

    def stop(self):
        if self._file:
            self._session.remove_torrent(self._file)
            self._file = None
            logger.info("Download stopped successfully.")
        else:
            logger.error("Download file instance not found.")

    def is_paused(self):
        return self._paused

    def __str__(self):
        pass

    def __repr__(self):
        pass

    def __call__(self):
        pass
