"""The steps of one receipt file: chain detection, extraction and checks, then the write.

Each step is separate, so the job can persist its result and a restart resumes at the next one.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from retail_receipts_import.adapters.gemini.images import UnreadableImage
from retail_receipts_import.adapters.postgres.chains import ChainReference
from retail_receipts_import.adapters.postgres.receipts import WriteKind, WriteResult
from retail_receipts_import.domain.chains import UNREADABLE
from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.pass1 import (
    Pass1Response,
    build_pass1_prompt,
    create_pass1_schema,
    is_supported_chain,
)
from retail_receipts_import.domain.chains.registry import PLUGINS
from retail_receipts_import.domain.extraction import (
    Classification,
    ExtractionClass,
    GeminiCallError,
)
from retail_receipts_import.domain.outcomes import FailureReason
from retail_receipts_import.domain.receipt import (
    NormalizedReceipt,
    ReceiptSource,
    check_consistency,
    check_total,
)

Generate = Callable[[bytes, str, str, type[BaseModel]], str]
Write = Callable[[uuid.UUID, NormalizedReceipt, ReceiptSource], WriteResult]
FindOtherSource = Callable[[str, datetime, ReceiptSource], uuid.UUID | None]
ReadChainReference = Callable[[], ChainReference]
Prepare = Callable[[bytes, str], bytes]
# The wait count makes repeated waits back off.
Classify = Callable[[GeminiCallError, int], Classification]


@dataclass(frozen=True)
class Ports:
    """External I/O ports and adapter callables used across pipeline stages."""

    generate: Generate
    write: Write
    find_other_source: FindOtherSource
    read_chain_reference: ReadChainReference
    prepare: Prepare
    classify: Classify


class ExtractionWait(Exception):
    """Gemini cannot answer now, or not until its configuration is fixed: the job waits."""

    def __init__(self, found: Classification, error: GeminiCallError) -> None:
        super().__init__(f"{found.kind}: {error}")
        self.kind = found.kind
        self.delay = found.delay
        self.error = error


@dataclass(frozen=True)
class ChainFound:
    """Outcome of pass-1 when a known retail chain is recognized."""

    pass1: Pass1Response


@dataclass(frozen=True)
class Extracted:
    """Outcome of pass-2 when receipt lines and settlements are normalized."""

    receipt: NormalizedReceipt


@dataclass(frozen=True)
class ChainWithdrawn:
    """The reference no longer supports the chain pass 1 found; the file is not at fault."""

    chain_id: str


@dataclass(frozen=True)
class Stored:
    """Final pipeline outcome when a receipt is successfully persisted."""

    receipt_id: uuid.UUID


@dataclass(frozen=True)
class Duplicate:
    """Final pipeline outcome when a receipt duplicates an already stored record."""

    receipt_id: uuid.UUID


@dataclass(frozen=True)
class Unsupported:
    """Pass-1 outcome when the receipt belongs to an unrecognized or inactive retail chain."""

    chain_id: str
    store_name: str | None = None


@dataclass(frozen=True)
class Invalid:
    """Pipeline failure outcome when receipt content fails validation or schema rules."""

    reason: FailureReason
    detail: str


Pass1Result = ChainFound | Unsupported | Invalid
Pass2Result = Extracted | ChainWithdrawn | Invalid
WriteOutcome = Stored | Duplicate


def detect_chain(path: Path, mime: str, ports: Ports, *, waits: int) -> Pass1Result:
    """Pass 1: which chain printed the receipt, with the reference as its vocabulary."""
    return _with_gemini(lambda: _detect_chain(path, mime, ports), ports, waits)


def extract(
    path: Path, mime: str, pass1: Pass1Response, ports: Ports, *, waits: int
) -> Pass2Result:
    """Pass 2 for the chain pass 1 found, then the OIB and consistency checks."""
    return _with_gemini(lambda: _extract(path, mime, pass1, ports), ports, waits)


def precheck(pass1: Pass1Response, source: ReceiptSource, ports: Ports) -> Duplicate | None:
    """Spares pass 2 for a resend: pass 1's printed time already names the stored receipt.

    Advisory: a time pass 1 misses or misreads just means pass 2 runs and the writer decides.
    """
    if pass1.purchase_date is None or pass1.purchase_time is None:
        return None
    purchased_at = PLUGINS[pass1.chain].normalize_pass1_time(
        pass1.purchase_date, pass1.purchase_time
    )
    if purchased_at is None:
        return None
    existing = ports.find_other_source(pass1.chain, purchased_at, source)
    return None if existing is None else Duplicate(existing)


def store(
    receipt_id: uuid.UUID, receipt: NormalizedReceipt, source: ReceiptSource, ports: Ports
) -> WriteOutcome:
    """Persists a normalized receipt to PostgreSQL, handling duplicate deduplication."""
    written = ports.write(receipt_id, receipt, source)
    if written.kind is WriteKind.DUPLICATE:
        return Duplicate(written.receipt_id)
    # Our own earlier write of this source is this receipt, stored.
    return Stored(written.receipt_id)


def _with_gemini[R](step: Callable[[], R], ports: Ports, waits: int) -> R | Invalid:
    """A Gemini failure caused by the file is `Invalid`; any other one raises `ExtractionWait`."""
    try:
        return step()
    except GeminiCallError as exc:
        failure = exc
    found = ports.classify(failure, waits)
    if found.kind is ExtractionClass.INVALID:
        return Invalid(
            FailureReason.NO_VALID_RESULT,
            f"gemini rejected the file: {failure.code} {failure.status} {failure.reason}",
        )
    # Outside the except block, so the wait does not drag the error in as its context.
    raise ExtractionWait(found, failure)


def _prepared(path: Path, mime: str, ports: Ports) -> bytes | Invalid:
    try:
        return ports.prepare(path.read_bytes(), mime)
    except UnreadableImage as exc:
        return Invalid(FailureReason.NO_VALID_RESULT, str(exc))


def _detect_chain(path: Path, mime: str, ports: Ports) -> Pass1Result:
    data = _prepared(path, mime, ports)
    if isinstance(data, Invalid):
        return data
    reference = ports.read_chain_reference()
    active_ids = tuple(chain.chain_id for chain in reference.chains)
    pass1_schema = create_pass1_schema(active_ids)
    pass1_prompt = build_pass1_prompt(reference.chains, PLUGINS)

    pass1_text = ports.generate(data, mime, pass1_prompt, pass1_schema)
    try:
        pass1 = pass1_schema.model_validate_json(pass1_text)
    except ValidationError as exc:
        return Invalid(
            FailureReason.NO_VALID_RESULT,
            f"pass-1 response fails schema ({exc.error_count()} errors)",
        )

    chosen = pass1.chain
    if chosen == UNREADABLE:
        return Invalid(FailureReason.NO_VALID_RESULT, "receipt is unreadable")
    if not is_supported_chain(chosen, set(active_ids), PLUGINS):
        store_name = (pass1.store_name or "").strip() or None
        return Unsupported(chain_id=chosen, store_name=store_name)
    return ChainFound(pass1)


def _extract(path: Path, mime: str, pass1: Pass1Response, ports: Ports) -> Pass2Result:
    # Read again rather than kept from pass 1, so an OIB the admin corrects applies at once.
    reference = ports.read_chain_reference()
    active_chains = {chain.chain_id: chain for chain in reference.chains}
    chosen = pass1.chain
    if not is_supported_chain(chosen, set(active_chains.keys()), PLUGINS):
        return ChainWithdrawn(chosen)
    data = _prepared(path, mime, ports)
    if isinstance(data, Invalid):
        return data

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
            FailureReason.TOTAL_SETTLEMENT_MISMATCH, f"total minus settlements is {difference}"
        )
    return Extracted(receipt)
