from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse
from urllib.request import urlopen


class TorrentInfo:
    def __init__(self, path, libtorrent):
        self._path = path
        self._lt = libtorrent
        self._info = self._load_torrent_info()

    @staticmethod
    def _is_remote_torrent(path):
        parsed = urlparse(path)
        return parsed.scheme in {"http", "https"}

    def _download_torrent_file(self):
        with urlopen(self._path) as response, NamedTemporaryFile(delete=False, suffix=".torrent") as temp_file:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                temp_file.write(chunk)
            return temp_file.name

    def _load_torrent_info(self):
        if not self._is_remote_torrent(self._path):
            return self._lt.torrent_info(self._path)

        temp_path = self._download_torrent_file()
        try:
            return self._lt.torrent_info(temp_path)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def show_info(self):
        pass

    def create_torrent_info(self):
        self._info = self._load_torrent_info()
        return self._info

    def __str__(self):
        pass

    def __repr__(self):
        pass

    def __call__(self):
        return self.create_torrent_info()
