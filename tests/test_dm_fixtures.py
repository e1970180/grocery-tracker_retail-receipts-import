"""Recorded DM responses against their hand-derived records, offline."""

import functools
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from retail_receipts_import.adapters.gemini import images
from retail_receipts_import.adapters.postgres.chains import ChainReference
from retail_receipts_import.adapters.postgres.receipts import WriteKind, WriteResult
from retail_receipts_import.app.pipeline import Ports, Stored
from retail_receipts_import.domain.chains import KnownChain
from retail_receipts_import.domain.chains.dm.schema import DmPass2
from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.registry import PLUGINS
from retail_receipts_import.domain.extraction import classify
from retail_receipts_import.domain.receipt import (
    LineKind,
    NormalizedReceipt,
    ReceiptSource,
    SettlementKind,
    check_consistency,
    check_total,
    telegram_source,
)
from tests.dm_samples import (
    CARD,
    CASH,
    CHANGE,
    DM_OIB,
    item,
    payment,
    response,
    storno_line,
    storno_marker,
)
from tests.steps import run_steps

FIXTURES = Path(__file__).parent / "fixtures"
DM_FIXTURES = FIXTURES / "dm"

CASE_FOLDERS = sorted(p for p in DM_FIXTURES.iterdir() if p.is_dir())


def test_all_recorded_cases_are_present() -> None:
    # A lost folder would otherwise just shrink the parametrized tests below.
    assert len(CASE_FOLDERS) == 9


@pytest.mark.parametrize("case", CASE_FOLDERS, ids=[case.name for case in CASE_FOLDERS])
def test_recorded_response_gives_the_confirmed_record(case: Path) -> None:
    receipt = PLUGINS["dm"].normalize((case / "pass2.json").read_text(encoding="utf-8"))
    expected = NormalizedReceipt.model_validate_json(
        (case / "expected.json").read_text(encoding="utf-8")
    )
    assert receipt == expected
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_recorded_storno_stores_only_the_lines_that_stand() -> None:
    receipt = PLUGINS["dm"].normalize((DM_FIXTURES / "48549" / "pass2.json").read_text("utf-8"))
    assert [(line.printed_text, line.printed_amount) for line in receipt.stored_lines()] == [
        ("Balea Med gel za tuš.300ml", Decimal("1.10")),
        ("Balea Pr.krema/kovrče150ml", Decimal("3.30")),
    ]


@pytest.mark.parametrize("case", CASE_FOLDERS, ids=[case.name for case in CASE_FOLDERS])
def test_pipeline_stores_recorded_dm_samples(case: Path, tmp_path: Path) -> None:
    pass2_text = (case / "pass2.json").read_text(encoding="utf-8")
    pass1_text = (case / "pass1.json").read_text(encoding="utf-8")
    expected_file = case / "expected.json"
    pdf_path = tmp_path / f"{case.name}.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")
    stored_id = uuid.uuid7()
    written_receipts: list[NormalizedReceipt] = []

    def fake_generate(data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        if schema is DmPass2:
            return pass2_text
        return pass1_text

    def fake_write(
        receipt_id: uuid.UUID, receipt: NormalizedReceipt, source: ReceiptSource
    ) -> WriteResult:
        written_receipts.append(receipt)
        return WriteResult(WriteKind.STORED, stored_id)

    reference = ChainReference(
        chains=(
            KnownChain("dm", "dm", ("DM", "dm"), (DM_OIB,)),
            KnownChain("spar", "Spar", ("SPAR", "Spar", "INTERSPAR"), ("46108893754",)),
        ),
        inactive_ids=(),
        rejected=(),
    )
    ports = Ports(
        generate=fake_generate,
        write=fake_write,
        find_other_source=lambda chain_id, purchased_at, source: None,
        read_chain_reference=lambda: reference,
        prepare=functools.partial(images.prepare, max_pixels=16_000_000),
        classify=functools.partial(classify, initial_s=600, cap_s=1800),
    )
    result = run_steps(
        pdf_path, "application/pdf", telegram_source(0, 1, buyer_name="tester"), ports
    )
    assert result == Stored(stored_id)
    expected = NormalizedReceipt.model_validate_json(expected_file.read_text(encoding="utf-8"))
    assert written_receipts == [expected]
    assert written_receipts[0].chain_id == "dm"


def test_dm_plugin_pass1_time_normalizer() -> None:
    dm = PLUGINS["dm"]
    # Zagreb daylight saving time (CEST is UTC+2): 18:42 local -> 16:42 UTC.
    assert dm.normalize_pass1_time("21.09.2024", "18:42") == datetime(
        2024, 9, 21, 16, 42, tzinfo=UTC
    )
    # Zagreb winter time (CET is UTC+1): 14:28 local -> 13:28 UTC.
    assert dm.normalize_pass1_time("15.12.2025", "14:28") == datetime(
        2025, 12, 15, 13, 28, tzinfo=UTC
    )
    assert dm.normalize_pass1_time("15.12.25", "14:28:00") == datetime(
        2025, 12, 15, 13, 28, tzinfo=UTC
    )
    # Unreadable or invalid dates/times return None and never raise.
    assert dm.normalize_pass1_time("invalid", "14:28") is None
    assert dm.normalize_pass1_time("15.12.2025", "invalid") is None
    assert dm.normalize_pass1_time("32.13.2025", "14:28:00") is None
    assert dm.normalize_pass1_time("", "") is None


def test_dm_plugin_seller_oib() -> None:
    dm = PLUGINS["dm"]
    assert dm.seller_oib(response()) == DM_OIB
    assert dm.seller_oib(response(seller_oib=f" {DM_OIB} ")) == DM_OIB
    assert dm.seller_oib(response(seller_oib=None)) is None
    assert dm.seller_oib(response(seller_oib="  ")) is None
    assert dm.seller_oib("not json") is None


def _property_names(schema: Any) -> list[str]:
    if isinstance(schema, dict):
        own = list(schema.get("properties", {}))
        return own + [name for value in schema.values() for name in _property_names(value)]
    if isinstance(schema, list):
        return [name for value in schema for name in _property_names(value)]
    return []


def test_dm_schema_asks_for_no_slip_or_terminal_field() -> None:
    names = _property_names(DmPass2.model_json_schema())
    assert "payments" in names
    for name in names:
        assert not re.search(r"\bpan\b|\btid\b|\bmid\b|\brrn\b|terminal", name, re.IGNORECASE), name


def test_matrix_card() -> None:
    # Card: two Maybelline 1 kom x 7,90 7,90 1, Ukupno 15,80, MASTERCARD EUR -15,80
    # -> two lines 7.90, card 15.80, total 15.80
    raw = response(
        lines=[
            item("Maybelline korekt /podočnjak", "1", "7,90", "7,90"),
            item("Maybelline kor. za podočnjak", "1", "7,90", "7,90"),
        ],
        total="15,80",
        payments=[payment(CARD, "-15,80")],
    )
    receipt = PLUGINS["dm"].normalize(raw)
    assert len(receipt.lines) == 2
    assert receipt.lines[0].printed_text == "Maybelline korekt /podočnjak"
    assert receipt.lines[0].quantity == Decimal(1)
    assert receipt.lines[0].unit_price == Decimal("7.90")
    assert receipt.lines[0].printed_amount == Decimal("7.90")
    assert receipt.lines[1].printed_text == "Maybelline kor. za podočnjak"
    assert receipt.lines[1].quantity == Decimal(1)
    assert receipt.lines[1].unit_price == Decimal("7.90")
    assert receipt.lines[1].printed_amount == Decimal("7.90")
    assert receipt.total == Decimal("15.80")
    assert len(receipt.settlements) == 1
    assert receipt.settlements[0].kind == SettlementKind.CARD
    assert receipt.settlements[0].amount == Decimal("15.80")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_storno() -> None:
    # Storno: two Balea Med gel 1,10, STORNO RETKA + -1 kom x -1,10, Balea Pr.krema 3,30
    # -> three printed sale lines + storno cancelling line 2; stored lines 1.10 and 3.30
    raw = response(
        lines=[
            item("Balea Med gel za tuš.300ml", "1", "1,10", "1,10"),
            item("Balea Med gel za tuš.300ml", "1", "1,10", "1,10"),
            storno_marker(),
            storno_line("Balea Med gel za tuš.300ml", "-1", "-1,10", "-1,10"),
            item("Balea Pr.krema/kovrče150ml", "1", "3,30", "3,30"),
        ],
        total="4,40",
        payments=[payment(CARD, "-4,40")],
    )
    receipt = PLUGINS["dm"].normalize(raw)
    assert len(receipt.lines) == 4
    assert receipt.lines[0].kind == LineKind.SALE
    assert receipt.lines[1].kind == LineKind.SALE
    assert receipt.lines[2].kind == LineKind.STORNO
    assert receipt.lines[2].cancels_line == 2
    assert receipt.lines[2].quantity == Decimal(-1)
    assert receipt.lines[2].unit_price == Decimal("-1.10")
    assert receipt.lines[2].printed_amount == Decimal("-1.10")
    assert receipt.lines[3].kind == LineKind.SALE

    stored = receipt.stored_lines()
    assert len(stored) == 2
    assert stored[0].printed_text == "Balea Med gel za tuš.300ml"
    assert stored[0].printed_amount == Decimal("1.10")
    assert stored[1].printed_text == "Balea Pr.krema/kovrče150ml"
    assert stored[1].printed_amount == Decimal("3.30")

    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_storno_unmatched() -> None:
    # Storno with no matching earlier sale line: unreadable
    raw = response(
        lines=[
            item("Balea Med gel za tuš.300ml", "1", "1,10", "1,10"),
            storno_marker(),
            storno_line("Other Item", "-1", "-1,10", "-1,10"),
        ],
        total="0,00",
        payments=[payment(CARD, "0,00")],
    )
    with pytest.raises(UnreadableReceipt, match="no matching earlier sale line"):
        PLUGINS["dm"].normalize(raw)


def test_matrix_cash_with_change() -> None:
    # Cash with change: GOTOVINA EUR -4,00, Povrat novaca EUR 0,75 -> cash 3.25
    raw = response(
        lines=[item("Balea krema za ruke", "1", "3,25", "3,25")],
        total="3,25",
        payments=[payment(CASH, "-4,00"), payment(CHANGE, "0,75")],
    )
    receipt = PLUGINS["dm"].normalize(raw)
    assert len(receipt.settlements) == 1
    assert receipt.settlements[0].kind == SettlementKind.CASH
    assert receipt.settlements[0].amount == Decimal("3.25")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_change_without_cash_row() -> None:
    # Change without exactly one cash row: unreadable
    raw = response(
        lines=[item("Balea krema", "1", "3,25", "3,25")],
        total="3,25",
        payments=[payment(CARD, "-4,00"), payment(CHANGE, "0,75")],
    )
    with pytest.raises(UnreadableReceipt, match="without exactly one cash row"):
        PLUGINS["dm"].normalize(raw)

    # A zero change row changes nothing, so a card receipt that prints one stays readable
    zero_change = response(
        lines=[item("Balea krema", "1", "3,25", "3,25")],
        total="3,25",
        payments=[payment(CARD, "-3,25"), payment(CHANGE, "0,00")],
    )
    assert PLUGINS["dm"].normalize(zero_change).settlements[0].amount == Decimal("3.25")


def test_matrix_branch_and_receipt_number() -> None:
    # Branch: Br. računa: 38588/K08H/1 -> branch K08H, receipt_number 38588/K08H/1
    raw = response(receipt_number="Br. računa: 38588/K08H/1")
    receipt = PLUGINS["dm"].normalize(raw)
    assert receipt.branch_number == "K08H"
    assert receipt.receipt_number == "38588/K08H/1"

    # Broj računa label
    raw_broj = response(receipt_number="Broj računa: 212915/K05F/2")
    receipt_broj = PLUGINS["dm"].normalize(raw_broj)
    assert receipt_broj.branch_number == "K05F"
    assert receipt_broj.receipt_number == "212915/K05F/2"

    # Fewer than three segments: unreadable
    raw_two_seg = response(receipt_number="38588/K08H")
    with pytest.raises(UnreadableReceipt, match="fewer than three segments"):
        PLUGINS["dm"].normalize(raw_two_seg)

    # Missing receipt number: unreadable
    raw_none = response(receipt_number=None)
    with pytest.raises(UnreadableReceipt, match="missing receipt number"):
        PLUGINS["dm"].normalize(raw_none)


def test_matrix_store_address() -> None:
    # Specific shop address
    raw_shop = response(store_address="Ulica Vice Vukova 6, 10000 ZAGREB")
    receipt_shop = PLUGINS["dm"].normalize(raw_shop)
    assert receipt_shop.store_address == "Ulica Vice Vukova 6, 10000 ZAGREB"
    assert receipt_shop.store_name is None

    # The header image prints street and city on two lines
    raw_two_lines = response(store_address="Av. Dubrovnik 16\n10000 ZAGREB")
    receipt_two_lines = PLUGINS["dm"].normalize(raw_two_lines)
    assert receipt_two_lines.store_address == "Av. Dubrovnik 16, 10000 ZAGREB"

    # A head office line beside the shop drops only that line
    raw_both = response(store_address="Ulica Vice Vukova 6\n10090 ZAGREB, Kovinska 5a")
    assert PLUGINS["dm"].normalize(raw_both).store_address == "Ulica Vice Vukova 6"

    # Head office address is filtered out
    raw_office = response(store_address="10090 ZAGREB, Kovinska 5a")
    receipt_office = PLUGINS["dm"].normalize(raw_office)
    assert receipt_office.store_address is None

    # Absent address
    raw_none = response(store_address=None)
    receipt_none = PLUGINS["dm"].normalize(raw_none)
    assert receipt_none.store_address is None


def test_matrix_header_time() -> None:
    # Header time: 15.12.2025 14:28 -> 2025-12-15 14:28 Zagreb -> 13:28 UTC
    raw = response(purchase_date="15.12.2025", purchase_time="14:28")
    receipt = PLUGINS["dm"].normalize(raw)
    assert receipt.purchased_at == datetime(2025, 12, 15, 13, 28, tzinfo=UTC)

    # Unreadable date or time: unreadable
    with pytest.raises(UnreadableReceipt, match="cannot be read"):
        PLUGINS["dm"].normalize(response(purchase_date="invalid"))
    with pytest.raises(UnreadableReceipt, match="cannot be read"):
        PLUGINS["dm"].normalize(response(purchase_time="invalid"))


def test_matrix_unknown_payment() -> None:
    # Unknown payment label: unreadable
    raw = response(payments=[payment("AMEX EUR", "-3,00")])
    with pytest.raises(UnreadableReceipt, match="not a known kind"):
        PLUGINS["dm"].normalize(raw)


def test_matrix_unknown_negative_row() -> None:
    # Negative row not after STORNO RETKA: unreadable
    raw = response(lines=[item("Item", "1", "1,00", "-1,00")])
    with pytest.raises(UnreadableReceipt, match="not after STORNO RETKA"):
        PLUGINS["dm"].normalize(raw)


def test_matrix_info_rows_dropped() -> None:
    # PDV table, Active Beauty, slip markers never enter lines or settlements
    raw = response(
        lines=[
            item("Maybelline korekt /podočnjak", "1", "7,90", "7,90"),
            item("St. PDV-a 1=25,00%", "1", "0,00", "0,00"),
            item("15 dm active beauty bod(a/ova)", "1", "0,00", "0,00"),
        ],
        payments=[
            payment(CARD, "-7,90"),
            payment("PDV 1,58", "0,00"),
        ],
        total="7,90",
    )
    receipt = PLUGINS["dm"].normalize(raw)
    assert len(receipt.lines) == 1
    assert receipt.lines[0].printed_text == "Maybelline korekt /podočnjak"
    assert len(receipt.settlements) == 1
    assert receipt.settlements[0].kind == SettlementKind.CARD


def test_line_model_errors_are_unreadable() -> None:
    # Zero quantity or invalid numbers wrapped in UnreadableReceipt
    raw = response(
        lines=[item("Maybelline korekt", "0", "7,90", "7,90")],
        total="7,90",
        payments=[payment(CARD, "-7,90")],
    )
    with pytest.raises(UnreadableReceipt, match="fails the model"):
        PLUGINS["dm"].normalize(raw)
