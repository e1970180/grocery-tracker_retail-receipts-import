from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from retail_receipts_import.adapters.telegram.client import (
    TelegramAPIError,
    TelegramClient,
    TelegramRetryExhaustedError,
)
from retail_receipts_import.adapters.telegram.download import (
    FileTooLarge,
    FileUnavailable,
    download_file,
)

SECRET = SecretStr("123456789:AAFakeTokenForTelegramClientTests_x")
LIMIT = 1000


def _client(file_result: dict[str, Any], downloads: list[str]) -> TelegramClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/getFile" in str(request.url):
            return httpx.Response(200, json={"ok": True, "result": file_result})
        downloads.append(str(request.url))
        return httpx.Response(200, content=b"%PDF-1.7")

    return TelegramClient(SECRET, transport=httpx.MockTransport(handler))


def test_downloads_the_file_getfile_confirms() -> None:
    downloads: list[str] = []
    client = _client({"file_id": "f", "file_size": 8, "file_path": "documents/a.pdf"}, downloads)
    assert download_file(client, "f", 8, LIMIT) == b"%PDF-1.7"
    assert downloads == [
        f"https://api.telegram.org/file/bot{SECRET.get_secret_value()}/documents/a.pdf"
    ]


@pytest.mark.parametrize("size", [LIMIT + 1, None, "12"])
def test_oversized_or_unconfirmed_size_is_never_downloaded(size: object) -> None:
    downloads: list[str] = []
    client = _client({"file_id": "f", "file_size": size, "file_path": "documents/a.pdf"}, downloads)
    with pytest.raises(FileTooLarge):
        download_file(client, "f", 8, LIMIT)
    assert downloads == []


def test_getfile_without_size_falls_back_to_the_declared_size() -> None:
    downloads: list[str] = []
    client = _client({"file_id": "f", "file_path": "documents/a.pdf"}, downloads)
    assert download_file(client, "f", 8, LIMIT) == b"%PDF-1.7"


def test_getfile_without_path_is_unavailable() -> None:
    client = _client({"file_id": "f", "file_size": 8}, [])
    with pytest.raises(FileUnavailable):
        download_file(client, "f", 8, LIMIT)


def _failing_client(getfile_status: int, download_status: int) -> TelegramClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/getFile" in str(request.url):
            if getfile_status != 200:
                return httpx.Response(
                    getfile_status, json={"ok": False, "description": "Bad Request"}
                )
            result = {"file_id": "f", "file_size": 8, "file_path": "documents/a.pdf"}
            return httpx.Response(200, json={"ok": True, "result": result})
        return httpx.Response(download_status, json={"ok": False, "description": "Not Found"})

    return TelegramClient(SECRET, transport=httpx.MockTransport(handler), sleep=lambda _: None)


@pytest.mark.parametrize(
    ("getfile_status", "download_status"),
    [(400, 200), (200, 404)],
    ids=["getfile-400", "download-404"],
)
def test_telegram_4xx_makes_the_file_unavailable(getfile_status: int, download_status: int) -> None:
    with pytest.raises(FileUnavailable) as info:
        download_file(_failing_client(getfile_status, download_status), "f", 8, LIMIT)
    assert isinstance(info.value.__cause__, TelegramAPIError)
    assert SECRET.get_secret_value() not in str(info.value)


@pytest.mark.parametrize(
    ("getfile_status", "download_status"),
    [(401, 200), (200, 401)],
    ids=["getfile", "download"],
)
def test_unauthorized_is_not_the_files_fault(getfile_status: int, download_status: int) -> None:
    with pytest.raises(TelegramAPIError) as info:
        download_file(_failing_client(getfile_status, download_status), "f", 8, LIMIT)
    assert info.value.status_code == 401


@pytest.mark.parametrize(
    ("getfile_status", "download_status"),
    [(502, 200), (200, 503)],
    ids=["getfile", "download"],
)
def test_server_error_after_retries_is_not_the_files_fault(
    getfile_status: int, download_status: int
) -> None:
    with pytest.raises(TelegramRetryExhaustedError):
        download_file(_failing_client(getfile_status, download_status), "f", 8, LIMIT)
