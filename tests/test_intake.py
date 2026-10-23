from typing import Any

import pytest

from retail_receipts_import.domain.intake import (
    MAX_FILE_BYTES,
    Accepted,
    FileKind,
    accept,
    largest_photo_size,
)

ALLOWED = frozenset({12345})
PDF = {"file_id": "doc1", "file_size": 4096, "mime_type": "application/pdf", "file_name": "r.pdf"}


def _update(**fields: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": 10,
        "date": 1727092800,
        "chat": {"id": 12345, "type": "private"},
        "from": {"id": 12345, "first_name": "Ana", "last_name": "Horvat"},
    }
    message.update(fields)
    return {"update_id": 1, "message": message}


def test_pdf_from_an_allowlisted_private_chat_is_accepted() -> None:
    assert accept(_update(document=PDF), ALLOWED) == Accepted(
        chat_id=12345,
        message_id=10,
        buyer_name="Ana Horvat",
        file_id="doc1",
        kind=FileKind.DOCUMENT,
        mime="application/pdf",
        declared_size=4096,
    )


def test_photo_takes_the_largest_size_as_jpeg() -> None:
    sizes = [
        {"file_id": "small", "width": 90, "height": 160, "file_size": 1000},
        {"file_id": "large", "width": 720, "height": 1280, "file_size": 90000},
    ]
    accepted = accept(_update(photo=sizes, caption="receipt"), ALLOWED)
    assert accepted is not None
    assert (accepted.file_id, accepted.kind, accepted.mime) == (
        "large",
        FileKind.PHOTO,
        "image/jpeg",
    )


@pytest.mark.parametrize("mime", ["image/jpeg", "image/png", "image/webp"])
def test_image_documents_are_accepted(mime: str) -> None:
    accepted = accept(_update(document={**PDF, "mime_type": mime}), ALLOWED)
    assert accepted is not None
    assert accepted.mime == mime


@pytest.mark.parametrize(
    "update",
    [
        _update(document=PDF, **{"from": {"id": 99999, "first_name": "X"}}),
        _update(document=PDF, chat={"id": -100123, "type": "supergroup"}),
        _update(document=PDF, chat={"id": -100123, "type": "group"}),
        _update(document=PDF, message_id=0),
        _update(document=PDF, business_connection_id="b1"),
        {"update_id": 1, "edited_message": _update(document=PDF)["message"]},
        _update(text="hello"),
        _update(sticker={"file_id": "s"}),
        _update(video={"file_id": "v", "file_size": 10, "mime_type": "video/mp4"}),
        _update(animation={"file_id": "a"}, document={**PDF, "mime_type": "image/png"}),
        _update(document={**PDF, "mime_type": "image/heic"}),
        _update(document={**PDF, "mime_type": "application/zip"}),
        _update(document={**PDF, "file_size": MAX_FILE_BYTES + 1}),
        _update(document={k: v for k, v in PDF.items() if k != "file_size"}),
        _update(photo=[]),
        _update(photo=[{"file_id": "p", "width": 10, "height": 10}]),
        {"update_id": 1},
        {"update_id": 1, "message": "not a dict"},
    ],
    ids=[
        "not-allowlisted",
        "supergroup",
        "group",
        "message-id-zero",
        "business-connection",
        "edited-message",
        "text",
        "sticker",
        "video",
        "animation-as-document",
        "heic",
        "zip",
        "over-20-mb",
        "unknown-size",
        "empty-photo",
        "photo-without-size",
        "no-message",
        "malformed-message",
    ],
)
def test_not_a_receipt_we_take(update: dict[str, Any]) -> None:
    assert accept(update, ALLOWED) is None


def test_exactly_20_mb_is_accepted() -> None:
    assert accept(_update(document={**PDF, "file_size": MAX_FILE_BYTES}), ALLOWED) is not None


def test_buyer_name_falls_back_to_the_user_id() -> None:
    accepted = accept(_update(document=PDF, **{"from": {"id": 12345, "first_name": " "}}), ALLOWED)
    assert accepted is not None
    assert accepted.buyer_name == "12345"


def test_largest_photo_size_selects_max_area() -> None:
    sizes: list[Any] = [
        {"file_id": "small", "width": 100, "height": 100, "file_size": 1000},
        {"file_id": "largest", "width": 800, "height": 600, "file_size": 25000},
        {"file_id": "medium", "width": 300, "height": 200, "file_size": 4000},
    ]
    largest = largest_photo_size(sizes)
    assert largest is not None
    assert largest["file_id"] == "largest"
