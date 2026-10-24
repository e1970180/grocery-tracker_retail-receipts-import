"""Runs the pipeline steps back to back, as a job does when nothing waits in between.

The dedup pre-check is left out, so pass 2 always runs, whatever is already stored.
"""

import uuid
from pathlib import Path

from retail_receipts_import.app.pipeline import (
    ChainFound,
    Extracted,
    Pass1Result,
    Pass2Result,
    Ports,
    WriteOutcome,
    detect_chain,
    extract,
    store,
)
from retail_receipts_import.domain.receipt import ReceiptSource

NEW_RECEIPT_ID = uuid.UUID(int=99)


def run_steps(
    path: Path, mime: str, source: ReceiptSource, ports: Ports
) -> Pass1Result | Pass2Result | WriteOutcome:
    found = detect_chain(path, mime, ports, waits=0)
    if not isinstance(found, ChainFound):
        return found
    extracted = extract(path, mime, found.pass1, ports, waits=0)
    if not isinstance(extracted, Extracted):
        return extracted
    return store(NEW_RECEIPT_ID, extracted.receipt, source, ports)
