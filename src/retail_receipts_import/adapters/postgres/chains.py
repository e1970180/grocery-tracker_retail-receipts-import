"""Reads the admin-owned chain reference through its versioned view."""

import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import psycopg

from retail_receipts_import.domain.chains import RESERVED_IDS, KnownChain, is_chain_id

# No WHERE clause: filtering on `active` in SQL would hide a NULL `active` and a duplicate id
# whose other copy is inactive, both of which must be reported. No ORDER BY either: a retyped
# `chain_id` would fail the whole query on a collation, instead of being rejected per row.
QUERY = (
    "SELECT chain_id, display_name, aliases, country_code, tax_numbers, active "
    "FROM public.chains_v1"
)

COUNTRY_CODE_PATTERN = re.compile(r"[A-Z]{2}")

# The reference is missing or unreadable for this role: undefined table, schema or column, or
# no privilege. Anything else, notably connection loss, is the caller's to handle as is.
STRUCTURAL_SQLSTATES = frozenset({"42P01", "3F000", "42703", "42501"})

# Connection loss and shutdown: SQLSTATE class 08, 57P01–57P03, or a connection error with no code.
CONNECTION_SQLSTATE_CLASSES = frozenset({"08"})
CONNECTION_SQLSTATES = frozenset({"57P01", "57P02", "57P03"})


def is_connection_error(exc: BaseException) -> bool:
    """Tells PostgreSQL connection-loss and shutdown errors from query faults or bugs."""
    if not isinstance(exc, psycopg.Error):
        return False
    if exc.sqlstate is not None:
        return (
            exc.sqlstate[:2] in CONNECTION_SQLSTATE_CLASSES or exc.sqlstate in CONNECTION_SQLSTATES
        )
    return isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))


class RejectReason(StrEnum):
    """Reason why a row in public.chains_v1 was rejected during reference validation."""

    INVALID_SLUG = "invalid_slug"
    RESERVED_ID = "reserved_id"
    NULL_FIELD = "null_field"
    BAD_ALIASES = "bad_aliases"
    BAD_COUNTRY_CODE = "bad_country_code"
    BAD_TAX_NUMBERS = "bad_tax_numbers"
    DUPLICATE_ID = "duplicate_id"


@dataclass(frozen=True)
class RejectedRow:
    """An invalid chain reference row rejected during sanity validation."""

    chain_id: str | None
    reason: RejectReason


@dataclass(frozen=True)
class ChainReference:
    """Validated in-memory snapshot of retail chains from public.chains_v1."""

    chains: tuple[KnownChain, ...]
    inactive_ids: tuple[str, ...]
    rejected: tuple[RejectedRow, ...]


class ChainReferenceError(Exception):
    """The reference view cannot be read: it, a column or the privilege on it is missing."""


def read_chain_reference(conn: psycopg.Connection[tuple[Any, ...]]) -> ChainReference:
    """Reads public.chains_v1, separating active, inactive, and rejected chains."""
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
    for chain_id, display_name, aliases, country_code, tax_numbers, active in rows:
        reason = _row_fault(chain_id, display_name, aliases, country_code, tax_numbers, active)
        if reason is None and id_counts[chain_id] > 1:
            reason = RejectReason.DUPLICATE_ID
        if reason is not None:
            rejected.append(RejectedRow(chain_id if isinstance(chain_id, str) else None, reason))
        elif active:
            chains.append(
                KnownChain(
                    chain_id, display_name, tuple(aliases), country_code, tuple(tax_numbers or ())
                )
            )
        else:
            inactive.append(chain_id)
    return ChainReference(
        chains=tuple(sorted(chains, key=lambda chain: chain.chain_id)),
        inactive_ids=tuple(sorted(inactive)),
        rejected=tuple(rejected),
    )


def _row_fault(
    chain_id: object,
    display_name: object,
    aliases: object,
    country_code: object,
    tax_numbers: object,
    active: object,
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
    if aliases is None or country_code is None:
        return RejectReason.NULL_FIELD
    # A text column would arrive as str, and tuple("DM") is ("D", "M").
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a for a in aliases):
        return RejectReason.BAD_ALIASES
    if not isinstance(country_code, str) or not COUNTRY_CODE_PATTERN.fullmatch(country_code):
        return RejectReason.BAD_COUNTRY_CODE
    # NULL and [] both mean the chain prints no tax identifier.
    if tax_numbers is None:
        return None
    # The text form arrives as str and a nested array as lists, neither of which is usable.
    if not isinstance(tax_numbers, list) or not all(
        isinstance(n, str) and n.strip() and "," not in n for n in tax_numbers
    ):
        return RejectReason.BAD_TAX_NUMBERS
    # isdigit alone also accepts non-ASCII digits such as "²".
    if country_code == "HR" and not all(
        len(n) == 11 and n.isascii() and n.isdigit() for n in tax_numbers
    ):
        return RejectReason.BAD_TAX_NUMBERS
    return None
