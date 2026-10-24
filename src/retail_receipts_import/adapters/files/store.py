"""Receipt files on the compose volume, named after their source so a job can find its file."""

import os
from pathlib import Path

from retail_receipts_import.domain.intake import ACCEPTED_MIME_TYPES


class FileStore:
    """Manages atomic persistence and path resolution for receipt files on the compose volume."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self._root = root

    def path_for(self, chat_id: int, message_id: int, mime: str) -> Path:
        """Derives a deterministic receipt file path from chat, message, and MIME type."""
        return self._root / f"{chat_id}_{message_id}.{ACCEPTED_MIME_TYPES[mime]}"

    def save(self, path: Path, data: bytes) -> None:
        """Atomically writes file bytes to disk using a temporary file and directory sync."""
        # Synced before the job leaves `received`, so a power cut never leaves a job pointing
        # at an empty file; a crash before the rename only means downloading again.
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        # The rename itself is durable only once the directory is synced.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def delete(self, path: Path) -> None:
        """Removes the stored receipt file if it exists."""
        # A job that failed before its download, or a second sweep, has no file to delete.
        path.unlink(missing_ok=True)
