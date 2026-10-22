"""Loads the user- and admin-facing texts file and refuses an incomplete one at startup."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from retail_receipts_import.domain.outcomes import (
    OUTCOMES_WITH_ADMIN_MESSAGE,
    OUTCOMES_WITH_REACTION,
    OUTCOMES_WITH_SENDER_MESSAGE,
    FailureReason,
    Outcome,
)

# Telegram rejects any other reaction, and only when the reaction is sent, so a typo
# would surface as a silently missing reaction. Matching is exact: no U+FE0F variants.
# Source: Bot API, ReactionTypeEmoji.
TELEGRAM_REACTION_EMOJI = frozenset(
    {
        "❤", "👍", "👎", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", "🤩",
        "🤮", "💩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳", "❤‍\U0001f525",
        "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕",
        "😈", "😴", "😭", "🤓", "👻", "\U0001f468‍\U0001f4bb", "👀", "🎃", "🙈", "😇",
        "😨", "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿", "🆒", "💘", "🙉",
        "🦄", "😘", "💊", "🙊", "😎", "👾", "\U0001f937‍♂", "🤷",
        "\U0001f937‍♀", "😡",
    }
)  # fmt: skip

type TextKey = Outcome | FailureReason


class TextsError(Exception):
    """The texts file is missing, unreadable or incomplete."""


@dataclass(frozen=True)
class Texts:
    reactions: dict[Outcome, str]
    sender_messages: dict[TextKey, str]
    admin_messages: dict[TextKey, str]


def load_texts(path: Path) -> Texts:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TextsError(f"texts file {path}: {exc}") from exc

    reasons = set(FailureReason)
    reactions = _section(raw, path, "reactions", OUTCOMES_WITH_REACTION)
    for key, emoji in reactions.items():
        if emoji not in TELEGRAM_REACTION_EMOJI:
            raise TextsError(
                f"texts file {path}: reactions.{key} is {emoji!r}, not a Telegram reaction emoji"
            )
    sender = _section(raw, path, "sender_messages", OUTCOMES_WITH_SENDER_MESSAGE | reasons)
    admin = _section(raw, path, "admin_messages", OUTCOMES_WITH_ADMIN_MESSAGE | reasons)
    return Texts(
        reactions={Outcome(k): v for k, v in reactions.items()},
        sender_messages=_keyed(sender),
        admin_messages=_keyed(admin),
    )


def _section(
    raw: dict[str, object], path: Path, name: str, required: frozenset[TextKey] | set[TextKey]
) -> dict[str, str]:
    table = raw.get(name)
    if not isinstance(table, dict):
        raise TextsError(f"texts file {path}: missing table [{name}]")
    expected = {str(key) for key in required}
    if missing := sorted(expected - table.keys()):
        raise TextsError(f"texts file {path}: missing keys {_dotted(name, missing)}")
    # Closed set: an extra key is a typo or a stale text nobody reads.
    if unknown := sorted(table.keys() - expected):
        raise TextsError(f"texts file {path}: unknown keys {_dotted(name, unknown)}")
    for key, value in table.items():
        if not isinstance(value, str) or not value.strip():
            raise TextsError(f"texts file {path}: {name}.{key} must be a non-empty string")
    return {str(k): str(v) for k, v in table.items()}


def _dotted(table: str, keys: list[str]) -> str:
    return ", ".join(f"{table}.{key}" for key in keys)


def _keyed(section: dict[str, str]) -> dict[TextKey, str]:
    outcomes = {str(o) for o in Outcome}
    return {(Outcome(k) if k in outcomes else FailureReason(k)): v for k, v in section.items()}
