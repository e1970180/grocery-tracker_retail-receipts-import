"""One receipt file of a known chain, from the model's reading to a stored receipt."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from retail_receipts_import.adapters.postgres.receipts import WriteKind, WriteResult
from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.registry import PLUGINS
from retail_receipts_import.domain.outcomes import FailureReason
from retail_receipts_import.domain.receipt import (
    NormalizedReceipt,
    ReceiptSource,
    check_consistency,
    check_total,
)

Generate = Callable[[bytes, str, str, type[BaseModel]], str]
Write = Callable[[uuid.UUID, NormalizedReceipt, ReceiptSource], WriteResult]


@dataclass(frozen=True)
class Ports:
    generate: Generate
    write: Write


@dataclass(frozen=True)
class Stored:
    receipt_id: uuid.UUID


@dataclass(frozen=True)
class Duplicate:
    receipt_id: uuid.UUID


@dataclass(frozen=True)
class Unsupported:
    chain_id: str


@dataclass(frozen=True)
class Invalid:
    reason: FailureReason
    detail: str


Result = Stored | Duplicate | Unsupported | Invalid


def process_file(
    path: Path, mime: str, chain_id: str, source: ReceiptSource, ports: Ports
) -> Result:
    """Reads, normalizes, checks and stores one receipt. Gemini and SDK errors propagate."""
    plugin = PLUGINS.get(chain_id)
    if plugin is None:
        return Unsupported(chain_id)

    response = ports.generate(path.read_bytes(), mime, plugin.pass2_prompt, plugin.pass2_schema)
    try:
        receipt = plugin.normalize(response)
    except UnreadableReceipt as exc:
        return Invalid(FailureReason.NO_VALID_RESULT, str(exc))

    # Checked here as well as in the writer, so a mismatch is an outcome and not an exception.
    if difference := check_consistency(receipt):
        return Invalid(
            FailureReason.ITEMS_SETTLEMENT_MISMATCH, f"lines minus settlements is {difference}"
        )
    if difference := check_total(receipt):
        return Invalid(
            FailureReason.TOTAL_SETTLEMENT_MISMATCH, f"total minus card and cash is {difference}"
        )

    written = ports.write(uuid.uuid7(), receipt, source)
    if written.kind is WriteKind.DUPLICATE:
        return Duplicate(written.receipt_id)
    # Our own earlier write of this source is this receipt, stored.
    return Stored(written.receipt_id)
