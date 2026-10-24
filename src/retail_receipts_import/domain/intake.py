"""Which Telegram messages become receipt jobs: the sender gate and the accepted file types.

Pure: the update is untrusted data, so every field is type-checked and nothing here raises.
The gate rules come from the telegram_core reference pack.
"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Mime type to local file extension. Gemini reads all four; HEIC is left out because the
# pinned Pillow cannot open it for the image preprocessing that shares this list.
ACCEPTED_MIME_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}
# The Bot API's getFile download limit.
MAX_FILE_BYTES = 20 * 1024 * 1024
# Telegram sends every photo as JPEG.
PHOTO_MIME = "image/jpeg"

# Messages sent on someone else's behalf, never by the family member to the bot.
_THIRD_PARTY_FIELDS = frozenset({"business_connection_id", "guest_query_id"})


class FileKind(StrEnum):
    PHOTO = "photo"
    DOCUMENT = "document"


@dataclass(frozen=True)
class Accepted:
    chat_id: int
    message_id: int
    buyer_name: str
    file_id: str
    kind: FileKind
    mime: str
    declared_size: int


@dataclass(frozen=True)
class NotAccepted:
    """A family member's own message that is not a receipt we take; it gets a reaction only."""

    chat_id: int
    message_id: int


def accept(update: Any, allowed_user_ids: Collection[int]) -> Accepted | NotAccepted | None:
    """The job to create for this update, NotAccepted for a family member's other content,
    or None when the update is not ours to answer at all."""
    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict) or not _authorized(message, allowed_user_ids):
        return None
    if message.keys() & _THIRD_PARTY_FIELDS:
        return None
    refused = NotAccepted(chat_id=message["chat"]["id"], message_id=message["message_id"])
    # Telegram also sets `document` on an animation, so an animation must not pass as one.
    if "animation" in message:
        return refused
    found = _photo(message.get("photo")) or _document(message.get("document"))
    if found is None:
        return refused
    file_id, kind, mime, size = found
    return Accepted(
        chat_id=message["chat"]["id"],
        message_id=message["message_id"],
        buyer_name=_buyer_name(message["from"]),
        file_id=file_id,
        kind=kind,
        mime=mime,
        declared_size=size,
    )


def largest_photo_size(sizes: list[Any]) -> dict[str, Any] | None:
    """The PhotoSize with the greatest pixel area, tie-broken by file size."""
    candidates = [s for s in sizes if isinstance(s, dict)]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda s: (_int(s.get("width")) * _int(s.get("height")), _int(s.get("file_size"))),
    )


def _authorized(message: dict[str, Any], allowed_user_ids: Collection[int]) -> bool:
    sender = message.get("from")
    sender_id = sender.get("id") if isinstance(sender, dict) else None
    chat = message.get("chat")
    chat_type = chat.get("type") if isinstance(chat, dict) else None
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    message_id = message.get("message_id")
    return (
        isinstance(sender_id, int)
        and sender_id in allowed_user_ids
        and chat_type == "private"
        and isinstance(chat_id, int)
        and isinstance(message_id, int)
        and message_id > 0
    )


def _photo(sizes: Any) -> tuple[str, FileKind, str, int] | None:
    if not isinstance(sizes, list):
        return None
    largest = largest_photo_size(sizes)
    if largest is None:
        return None
    return _sized(largest.get("file_id"), FileKind.PHOTO, PHOTO_MIME, largest.get("file_size"))


def _document(document: Any) -> tuple[str, FileKind, str, int] | None:
    if not isinstance(document, dict):
        return None
    mime = document.get("mime_type")
    if mime not in ACCEPTED_MIME_TYPES:
        return None
    return _sized(document.get("file_id"), FileKind.DOCUMENT, mime, document.get("file_size"))


def _sized(
    file_id: Any, kind: FileKind, mime: str, size: Any
) -> tuple[str, FileKind, str, int] | None:
    # An unconfirmed size could be anything, so it is refused like an oversized one.
    if not isinstance(file_id, str) or not file_id:
        return None
    if not isinstance(size, int) or size > MAX_FILE_BYTES:
        return None
    return file_id, kind, mime, size


def _buyer_name(sender: dict[str, Any]) -> str:
    parts = [sender.get("first_name"), sender.get("last_name")]
    name = " ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
    # The stored receipt needs a buyer; Telegram always sends first_name, but not trusted to.
    return name or str(sender["id"])


def _int(value: Any) -> int:
    return value if isinstance(value, int) else 0
