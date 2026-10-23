"""Downloads one accepted file, with the reference pack's size checks around getFile."""

from retail_receipts_import.adapters.telegram.client import TelegramAPIError, TelegramClient

# A revoked bot token fails every call, not this file, so it is not the file's fault.
_UNAUTHORIZED = 401


class FileTooLarge(Exception):
    """getFile reported, or failed to confirm, a size the Bot API cannot deliver."""


class FileUnavailable(Exception):
    """Telegram does not serve the file: a 4xx from getFile or the download, or no path."""


def download_file(
    client: TelegramClient, file_id: str, declared_size: int, max_bytes: int
) -> bytes:
    try:
        info = client.get_file(file_id)
        # A size Telegram does not confirm is treated as too large, so the bytes never reach memory.
        size = info.get("file_size", declared_size)
        if not isinstance(size, int) or size > max_bytes:
            raise FileTooLarge(f"getFile size {size!r} exceeds {max_bytes}")
        file_path = info.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            raise FileUnavailable("getFile returned no file_path")
        return client.download_file(file_path)
    except TelegramAPIError as exc:
        if exc.status_code == _UNAUTHORIZED:
            raise
        # The message names the method, never the URL, so the token stays out of it.
        raise FileUnavailable(str(exc)) from exc
