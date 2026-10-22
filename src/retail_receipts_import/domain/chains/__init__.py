"""Known retail chains, as the admin-owned reference describes them."""

import re
from dataclasses import dataclass

# The id is stored with every receipt and keys deduplication, so it must stay a plain slug.
CHAIN_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,31}")

# Pass 1 may answer with these instead of a known chain; the reference must never use them.
OTHER = "other"
UNREADABLE = "unreadable"
RESERVED_IDS = frozenset({OTHER, UNREADABLE})


def is_chain_id(value: str) -> bool:
    # fullmatch, because `$` would also accept a trailing newline.
    return CHAIN_ID_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class KnownChain:
    chain_id: str
    display_name: str
    aliases: tuple[str, ...]
