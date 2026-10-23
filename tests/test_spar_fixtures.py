"""Recorded Spar responses against their hand-derived records, offline.

Each case is `tests/fixtures/spar/<last 4 digits>/` with the recorded `pass2.json` and the
owner-confirmed `expected.json`. With no case recorded yet, the parametrized test is skipped.
"""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from retail_receipts_import.adapters.postgres.chains import ChainReference
from retail_receipts_import.adapters.postgres.receipts import WriteKind, WriteResult
from retail_receipts_import.app.pipeline import Ports, Stored, process_file
from retail_receipts_import.domain.chains import KnownChain
from retail_receipts_import.domain.chains.registry import PLUGINS
from retail_receipts_import.domain.chains.spar.schema import SparPass2
from retail_receipts_import.domain.receipt import (
    NormalizedReceipt,
    ReceiptSource,
    check_consistency,
    check_total,
    telegram_source,
)
from tests.spar_samples import pass1_response, response

FIXTURES = Path(__file__).parent / "fixtures"
CASES = sorted(
    path.parent
    for path in (FIXTURES / "spar").glob("*/pass2.json")
    if (path.parent / "expected.json").is_file()
)
# Card slip fields and card numbers, masked or not; none of them may be committed.
CARD_DATA = re.compile(r"\b(?:TID|MID|RRN|AID)\b|\d{4,6}\*{4,}\d{4}|(?<!\d)\d{13,19}(?!\d)")


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_recorded_response_gives_the_confirmed_record(case: Path) -> None:
    receipt = PLUGINS["spar"].normalize((case / "pass2.json").read_text(encoding="utf-8"))
    expected = NormalizedReceipt.model_validate_json(
        (case / "expected.json").read_text(encoding="utf-8")
    )
    assert receipt == expected
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_pipeline_stores_recorded_spar_samples(case: Path, tmp_path: Path) -> None:
    pass2_text = (case / "pass2.json").read_text(encoding="utf-8")
    pass1_file = case / "pass1.json"
    if pass1_file.is_file():
        pass1_text = pass1_file.read_text(encoding="utf-8")
    else:
        # Synthesize pass 1 from pass 2 until pass-1 responses are live recorded.
        raw = SparPass2.model_validate_json(pass2_text)
        pass1_text = pass1_response(
            chain="spar",
            store_name=raw.store_name,
            purchase_date=raw.purchase_date,
            purchase_time=raw.purchase_time,
        )
    pdf_path = tmp_path / f"{case.name}.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")
    stored_id = uuid.uuid7()
    written_receipts: list[NormalizedReceipt] = []

    def fake_generate(data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        if schema is SparPass2:
            return pass2_text
        return pass1_text

    def fake_write(
        receipt_id: uuid.UUID, receipt: NormalizedReceipt, source: ReceiptSource
    ) -> WriteResult:
        written_receipts.append(receipt)
        return WriteResult(WriteKind.STORED, stored_id)

    reference = ChainReference(
        chains=(KnownChain("spar", "Spar", ("SPAR", "Spar", "INTERSPAR"), ("46108893754",)),),
        inactive_ids=(),
        rejected=(),
    )
    ports = Ports(
        generate=fake_generate,
        write=fake_write,
        read_chain_reference=lambda: reference,
    )
    result = process_file(
        pdf_path, "application/pdf", telegram_source(0, 1, buyer_name="tester"), ports
    )
    assert result == Stored(stored_id)
    expected = NormalizedReceipt.model_validate_json(
        (case / "expected.json").read_text(encoding="utf-8")
    )
    assert written_receipts == [expected]


def test_spar_plugin_pass1_time_normalizer() -> None:
    spar = PLUGINS["spar"]
    # Zagreb daylight saving time (CEST is UTC+2): 10:15 local -> 08:15 UTC.
    assert spar.normalize_pass1_time("18.05.2026.", "10:15") == datetime(
        2026, 5, 18, 8, 15, tzinfo=UTC
    )
    # Zagreb winter time (CET is UTC+1): 12:47 local -> 11:47 UTC.
    assert spar.normalize_pass1_time("22.03.2026", "12:47") == datetime(
        2026, 3, 22, 11, 47, tzinfo=UTC
    )
    # Unreadable or invalid dates/times return None and never raise.
    assert spar.normalize_pass1_time("invalid", "10:15") is None
    assert spar.normalize_pass1_time("18.05.2026", "invalid") is None
    assert spar.normalize_pass1_time("32.13.2030", "09:05") is None
    assert spar.normalize_pass1_time("", "") is None


def test_spar_plugin_seller_oib() -> None:
    spar = PLUGINS["spar"]
    assert spar.seller_oib(response()) == "46108893754"
    assert spar.seller_oib(response(seller_oib=" 46108893754 ")) == "46108893754"
    assert spar.seller_oib(response(seller_oib=None)) is None
    assert spar.seller_oib(response(seller_oib="  ")) is None
    assert spar.seller_oib("not json") is None


def test_fixtures_hold_no_card_data() -> None:
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            assert CARD_DATA.search(path.read_text(encoding="utf-8")) is None, path


def _property_names(schema: Any) -> list[str]:
    if isinstance(schema, dict):
        own = list(schema.get("properties", {}))
        return own + [name for value in schema.values() for name in _property_names(value)]
    if isinstance(schema, list):
        return [name for value in schema for name in _property_names(value)]
    return []


def test_schema_asks_for_no_card_or_terminal_field() -> None:
    names = _property_names(SparPass2.model_json_schema())
    assert "payments" in names
    for name in names:
        assert not re.search(r"card|pan|tid|mid|rrn|terminal|chain", name), name


def test_registry_keys_are_the_plugins_own_ids() -> None:
    assert "spar" in PLUGINS
    for chain_id, plugin in PLUGINS.items():
        assert plugin.chain_id == chain_id
