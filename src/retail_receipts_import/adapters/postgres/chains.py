"""Reads the admin-owned chain reference through its versioned view."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import psycopg

from retail_receipts_import.domain.chains import RESERVED_IDS, KnownChain, is_chain_id

# No WHERE clause: filtering on `active` in SQL would hide a NULL `active` and a duplicate id
# whose other copy is inactive, both of which must be reported. No ORDER BY either: a retyped
# `chain_id` would fail the whole query on a collation, instead of being rejected per row.
QUERY = "SELECT chain_id, display_name, aliases, active FROM public.chains_v1"

# The reference is missing or unreadable for this role: undefined table, schema or column, or
# no privilege. Anything else, notably connection loss, is the caller's to handle as is.
STRUCTURAL_SQLSTATES = frozenset({"42P01", "3F000", "42703", "42501"})


class RejectReason(StrEnum):
    INVALID_SLUG = "invalid_slug"
    RESERVED_ID = "reserved_id"
    NULL_FIELD = "null_field"
    BAD_ALIASES = "bad_aliases"
    DUPLICATE_ID = "duplicate_id"


@dataclass(frozen=True)
class RejectedRow:
    chain_id: str | None
    reason: RejectReason


@dataclass(frozen=True)
class ChainReference:
    chains: tuple[KnownChain, ...]
    inactive_ids: tuple[str, ...]
    rejected: tuple[RejectedRow, ...]


class ChainReferenceError(Exception):
    """The reference view cannot be read: it, a column or the privilege on it is missing."""


def read_chain_reference(conn: psycopg.Connection[tuple[Any, ...]]) -> ChainReference:
    try:
        rows = conn.execute(QUERY).fetchall()
    except psycopg.Error as exc:
        if exc.sqlstate in STRUCTURAL_SQLSTATES:
            raise ChainReferenceError(
                f"chain reference public.chains_v1 is unreadable (SQLSTATE {exc.sqlstate})"
            ) from exc
        raise
    return _validate(rows)


def _validate(rows: list[tuple[Any, ...]]) -> ChainReference:
    # A repeated id is ambiguous whichever copy is meant, so every copy is rejected.
    id_counts = Counter(row[0] for row in rows if isinstance(row[0], str))
    chains: list[KnownChain] = []
    inactive: list[str] = []
    rejected: list[RejectedRow] = []
    for chain_id, display_name, aliases, active in rows:
        reason = _row_fault(chain_id, display_name, aliases, active)
        if reason is None and id_counts[chain_id] > 1:
            reason = RejectReason.DUPLICATE_ID
        if reason is not None:
            rejected.append(RejectedRow(chain_id if isinstance(chain_id, str) else None, reason))
        elif active:
            chains.append(KnownChain(chain_id, display_name, tuple(aliases)))
        else:
            inactive.append(chain_id)
    return ChainReference(
        chains=tuple(sorted(chains, key=lambda chain: chain.chain_id)),
        inactive_ids=tuple(sorted(inactive)),
        rejected=tuple(rejected),
    )


def _row_fault(
    chain_id: object, display_name: object, aliases: object, active: object
) -> RejectReason | None:
    if chain_id is None:
        return RejectReason.NULL_FIELD
    if not isinstance(chain_id, str) or not is_chain_id(chain_id):
        return RejectReason.INVALID_SLUG
    if chain_id in RESERVED_IDS:
        return RejectReason.RESERVED_ID
    # A blank name or a non-boolean flag is as unusable as a missing one.
    if not isinstance(display_name, str) or not display_name.strip():
        return RejectReason.NULL_FIELD
    if not isinstance(active, bool):
        return RejectReason.NULL_FIELD
    if aliases is None:
        return RejectReason.NULL_FIELD
    # A text column would arrive as str, and tuple("DM") is ("D", "M").
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a for a in aliases):
        return RejectReason.BAD_ALIASES
    return None
