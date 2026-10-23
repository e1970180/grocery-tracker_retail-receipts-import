"""One receipt file, from chain detection to a stored receipt."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from retail_receipts_import.adapters.postgres.chains import ChainReference
from retail_receipts_import.adapters.postgres.receipts import WriteKind, WriteResult
from retail_receipts_import.domain.chains import UNREADABLE
from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.pass1 import (
    build_pass1_prompt,
    create_pass1_schema,
    is_supported_chain,
)
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
ReadChainReference = Callable[[], ChainReference]


@dataclass(frozen=True)
class Ports:
    generate: Generate
    write: Write
    read_chain_reference: ReadChainReference


@dataclass(frozen=True)
class Stored:
    receipt_id: uuid.UUID


@dataclass(frozen=True)
class Duplicate:
    receipt_id: uuid.UUID


@dataclass(frozen=True)
class Unsupported:
    chain_id: str
    store_name: str | None = None


@dataclass(frozen=True)
class Invalid:
    reason: FailureReason
    detail: str


Result = Stored | Duplicate | Unsupported | Invalid


def process_file(path: Path, mime: str, source: ReceiptSource, ports: Ports) -> Result:
    """Detects the chain (pass 1), then normalizes, guards and stores the receipt (pass 2)."""
    reference = ports.read_chain_reference()
    active_chains = {chain.chain_id: chain for chain in reference.chains}
    pass1_schema = create_pass1_schema(tuple(active_chains.keys()))
    pass1_prompt = build_pass1_prompt(reference.chains, PLUGINS)

    data = path.read_bytes()
    pass1_text = ports.generate(data, mime, pass1_prompt, pass1_schema)
    try:
        pass1 = pass1_schema.model_validate_json(pass1_text)
    except ValidationError as exc:
        return Invalid(
            FailureReason.NO_VALID_RESULT,
            f"pass-1 response fails schema ({exc.error_count()} errors)",
        )

    chosen = pass1.chain
    store_name = (pass1.store_name or "").strip() or None

    if chosen == UNREADABLE:
        return Invalid(FailureReason.NO_VALID_RESULT, "receipt is unreadable")

    if not is_supported_chain(chosen, set(active_chains.keys()), PLUGINS):
        return Unsupported(chain_id=chosen, store_name=store_name)

    plugin = PLUGINS[chosen]
    known_chain = active_chains[chosen]
    pass2_text = ports.generate(data, mime, plugin.pass2_prompt, plugin.pass2_schema)

    try:
        receipt = plugin.normalize(pass2_text)
    except UnreadableReceipt as exc:
        return Invalid(FailureReason.NO_VALID_RESULT, str(exc))

    # The printed OIB must belong to the chain in the reference; neither value enters the detail.
    printed_oib = plugin.seller_oib(pass2_text)
    if printed_oib is None or printed_oib not in known_chain.seller_oibs:
        return Invalid(FailureReason.NO_VALID_RESULT, "seller OIB does not match chain reference")

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
