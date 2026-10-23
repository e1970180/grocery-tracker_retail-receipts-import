"""Downloads one accepted file, with the reference pack's size checks around getFile."""

from retail_receipts_import.adapters.telegram.client import TelegramClient


class FileTooLarge(Exception):
    """getFile reported, or failed to confirm, a size the Bot API cannot deliver."""


class FileUnavailable(Exception):
    """getFile returned no path, so there is nothing to download."""


def download_file(
    client: TelegramClient, file_id: str, declared_size: int, max_bytes: int
) -> bytes:
    info = client.get_file(file_id)
    # A size Telegram does not confirm is treated as too large, so the bytes never reach memory.
    size = info.get("file_size", declared_size)
    if not isinstance(size, int) or size > max_bytes:
        raise FileTooLarge(f"getFile size {size!r} exceeds {max_bytes}")
    file_path = info.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        raise FileUnavailable("getFile returned no file_path")
    return client.download_file(file_path)
