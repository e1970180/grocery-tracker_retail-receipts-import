"""Recorded Kaufland responses against their hand-derived records, offline."""

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
from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.kaufland.schema import KauflandPass2
from retail_receipts_import.domain.chains.registry import PLUGINS
from retail_receipts_import.domain.extraction import classify
from retail_receipts_import.domain.receipt import (
    NormalizedReceipt,
    ReceiptSource,
    SettlementKind,
    check_consistency,
    check_total,
    telegram_source,
)
from tests.kaufland_samples import (
    CARD,
    CASH,
    CHANGE,
    KAUFLAND_OIB,
    SAMPLE_20260427_231253_PASS2,
    discount,
    item,
    payment,
    response,
    stedite,
)
from tests.steps import run_steps

FIXTURES = Path(__file__).parent / "fixtures"
KAUFLAND_FIXTURES = FIXTURES / "kaufland"

CASE_FOLDERS = sorted(p for p in KAUFLAND_FIXTURES.iterdir() if p.is_dir())


def test_all_recorded_cases_are_present() -> None:
    # A lost folder would otherwise just shrink the parametrized tests below.
    assert len(CASE_FOLDERS) == 8


@pytest.mark.parametrize("case", CASE_FOLDERS, ids=[case.name for case in CASE_FOLDERS])
def test_recorded_response_gives_the_confirmed_record(case: Path) -> None:
    receipt = PLUGINS["kaufland"].normalize((case / "pass2.json").read_text(encoding="utf-8"))
    expected = NormalizedReceipt.model_validate_json(
        (case / "expected.json").read_text(encoding="utf-8")
    )
    assert receipt == expected
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


@pytest.mark.parametrize("case", CASE_FOLDERS, ids=[case.name for case in CASE_FOLDERS])
def test_pipeline_stores_recorded_kaufland_samples(case: Path, tmp_path: Path) -> None:
    pass2_text = (case / "pass2.json").read_text(encoding="utf-8")
    pass1_text = (case / "pass1.json").read_text(encoding="utf-8")
    expected_file = case / "expected.json"
    pdf_path = tmp_path / f"{case.name}.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")
    stored_id = uuid.uuid7()
    written_receipts: list[NormalizedReceipt] = []

    def fake_generate(data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        if schema is KauflandPass2:
            return pass2_text
        return pass1_text

    def fake_write(
        receipt_id: uuid.UUID, receipt: NormalizedReceipt, source: ReceiptSource
    ) -> WriteResult:
        written_receipts.append(receipt)
        return WriteResult(WriteKind.STORED, stored_id)

    reference = ChainReference(
        chains=(
            KnownChain("kaufland", "Kaufland", ("KAUFLAND", "Kaufland"), (KAUFLAND_OIB,)),
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
    assert written_receipts[0].chain_id == "kaufland"


def test_kaufland_plugin_pass1_time_normalizer() -> None:
    kaufland = PLUGINS["kaufland"]
    # Zagreb winter time (CET is UTC+1): 12:33 local -> 11:33 UTC.
    assert kaufland.normalize_pass1_time("25.02.26", "12:33:51") == datetime(
        2026, 2, 25, 11, 33, tzinfo=UTC
    )
    assert kaufland.normalize_pass1_time("25.02.2026", "12:33") == datetime(
        2026, 2, 25, 11, 33, tzinfo=UTC
    )
    assert kaufland.normalize_pass1_time("25.02.26.", "12:33") == datetime(
        2026, 2, 25, 11, 33, tzinfo=UTC
    )
    # Zagreb daylight saving time (CEST is UTC+2): 15:54 local -> 13:54 UTC.
    assert kaufland.normalize_pass1_time("23.05.2026", "15:54:37") == datetime(
        2026, 5, 23, 13, 54, tzinfo=UTC
    )
    # Unreadable or invalid dates/times return None and never raise.
    assert kaufland.normalize_pass1_time("invalid", "12:33:51") is None
    assert kaufland.normalize_pass1_time("25.02.26", "invalid") is None
    assert kaufland.normalize_pass1_time("32.13.26", "12:33:00") is None
    assert kaufland.normalize_pass1_time("", "") is None


def test_kaufland_plugin_seller_oib() -> None:
    kaufland = PLUGINS["kaufland"]
    assert kaufland.seller_oib(response()) == KAUFLAND_OIB
    assert kaufland.seller_oib(response(seller_oib=f" {KAUFLAND_OIB} ")) == KAUFLAND_OIB
    assert kaufland.seller_oib(response(seller_oib=None)) is None
    assert kaufland.seller_oib(response(seller_oib="  ")) is None
    assert kaufland.seller_oib("not json") is None


def _property_names(schema: Any) -> list[str]:
    if isinstance(schema, dict):
        own = list(schema.get("properties", {}))
        return own + [name for value in schema.values() for name in _property_names(value)]
    if isinstance(schema, list):
        return [name for value in schema for name in _property_names(value)]
    return []


def test_kaufland_schema_asks_for_no_slip_or_terminal_field() -> None:
    names = _property_names(KauflandPass2.model_json_schema())
    assert "payments" in names
    for name in names:
        assert not re.search(r"\bpan\b|\btid\b|\bmid\b|\brrn\b|terminal", name, re.IGNORECASE), name


def test_matrix_card_discount() -> None:
    # Card discount: K.Voda 7L 2 * 1,45 2,90 then Kaufland Card% -0,88
    # -> qty 2, unit_price 1.45, printed 2.90, separate 0.88
    raw = response(
        lines=[
            item("K.Voda 7L", "2", "1,45", "2,90"),
            discount("Kaufland Card%", "-0,88"),
        ],
        total="2,02",
        payments=[payment(CARD, "2,02")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert len(receipt.lines) == 1
    line = receipt.lines[0]
    assert line.printed_text == "K.Voda 7L"
    assert line.quantity == Decimal(2)
    assert line.unit_price == Decimal("1.45")
    assert line.printed_amount == Decimal("2.90")
    assert line.separate_discount == Decimal("0.88")
    assert line.discount_text == "Kaufland Card%"
    assert line.effective_amount == Decimal("2.02")


def test_matrix_shelf_promo() -> None:
    # Shelf promo: Pileće… 0,774 kg * 1,40 1,08 then Štedite 30% ili 0,46 EUR!
    # -> printed 1.08, included 0.46, unit kg
    raw = response(
        lines=[
            item("Pileće file", "0,774", "1,40", "1,08", unit="kg"),
            stedite("Štedite 30% ili 0,46 EUR!", "0,46"),
        ],
        total="1,08",
        payments=[payment(CARD, "1,08")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert len(receipt.lines) == 1
    line = receipt.lines[0]
    assert line.printed_text == "Pileće file"
    assert line.quantity == Decimal("0.774")
    assert line.unit == "kg"
    assert line.unit_price == Decimal("1.40")
    assert line.printed_amount == Decimal("1.08")
    assert line.included_discount == Decimal("0.46")
    assert line.separate_discount == Decimal(0)
    assert line.discount_text is None
    assert line.regular_amount == Decimal("1.54")
    assert line.effective_amount == Decimal("1.08")

    # Štedite with no item above: unreadable
    no_item = response(
        lines=[stedite("Štedite 30% ili 0,46 EUR!", "0,46")],
        total="1,08",
        payments=[payment(CARD, "1,08")],
    )
    with pytest.raises(UnreadableReceipt, match="without preceding item"):
        PLUGINS["kaufland"].normalize(no_item)


def test_matrix_purchase_discount() -> None:
    # Purchase discount: K.kamilica2x70 1,84 then Popust na kupnju -0,37
    # -> printed 1.84, separate 0.37, discount_text Popust na kupnju
    raw = response(
        lines=[
            item("K.kamilica2x70", "1", None, "1,84"),
            discount("Popust na kupnju", "-0,37"),
        ],
        total="1,47",
        payments=[payment(CARD, "1,47")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert len(receipt.lines) == 1
    line = receipt.lines[0]
    assert line.printed_text == "K.kamilica2x70"
    assert line.quantity == Decimal(1)
    assert line.printed_amount == Decimal("1.84")
    assert line.separate_discount == Decimal("0.37")
    assert line.discount_text == "Popust na kupnju"
    assert line.effective_amount == Decimal("1.47")


def test_matrix_loyalty_card() -> None:
    # Loyalty card: Kaufland Card: xxxxx8265 -> loyalty_card_number xxxxx8265; absent: None
    receipt = PLUGINS["kaufland"].normalize(response(loyalty_card="xxxxx8265"))
    assert receipt.loyalty_card_number == "xxxxx8265"

    receipt_with_prefix = PLUGINS["kaufland"].normalize(
        response(loyalty_card="Kaufland Card: xxxxx8265")
    )
    assert receipt_with_prefix.loyalty_card_number == "xxxxx8265"

    receipt_none = PLUGINS["kaufland"].normalize(response(loyalty_card=None))
    assert receipt_none.loyalty_card_number is None


def test_matrix_deposit_return() -> None:
    # Deposit return: ambalaža - PET * 14 * 0,10 -1,40 -> deposit_refund 1.40, not a line
    raw = response(
        lines=[
            item("K.Voda 7L", "2", "1,45", "2,90"),
            discount("ambalaža - PET * 14 * 0,10", "-1,40"),
        ],
        total="1,50",
        payments=[payment(CARD, "1,50")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert receipt.total == Decimal("2.90")
    assert len(receipt.lines) == 1
    assert receipt.lines[0].printed_text == "K.Voda 7L"
    assert len(receipt.settlements) == 2
    assert receipt.settlements[0].kind == SettlementKind.CARD
    assert receipt.settlements[0].amount == Decimal("1.50")
    assert receipt.settlements[1].kind == SettlementKind.DEPOSIT_REFUND
    assert receipt.settlements[1].amount == Decimal("1.40")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_refund_beats_purchase_synthetic() -> None:
    # Refund beats purchase: lines 1,00, refunds 3,00, Za platiti -2,00, cash -2,00
    # -> stored; total 1.00, cash -2.00
    raw = response(
        lines=[
            item("K.kamilica", "1", None, "1,00"),
            discount("ambalaža - PET", "-3,00"),
        ],
        total="-2,00",
        payments=[payment(CASH, "-2,00")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert receipt.total == Decimal("1.00")
    assert len(receipt.settlements) == 2
    assert receipt.settlements[0].kind == SettlementKind.CASH
    assert receipt.settlements[0].amount == Decimal("-2.00")
    assert receipt.settlements[1].kind == SettlementKind.DEPOSIT_REFUND
    assert receipt.settlements[1].amount == Decimal("3.00")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_kaufland_misread_amount_to_pay_fails_check_total() -> None:
    # Lines and payments agree (2.00), but printed amount to pay is off by 0,01.
    raw = response(
        lines=[item("Kruh", "1", None, "2,00")],
        total="2,01",
        payments=[payment(CARD, "2,00")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert check_consistency(receipt) is None
    assert check_total(receipt) == Decimal("0.01")


def test_matrix_cash_with_change() -> None:
    # Cash with change: Euro EUR 50,00, Za vratiti 6,33 -> cash 43.67
    raw = response(
        total="43,67",
        payments=[payment(CASH, "50,00"), payment(CHANGE, "6,33")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert len(receipt.settlements) == 1
    assert receipt.settlements[0].kind == SettlementKind.CASH
    assert receipt.settlements[0].amount == Decimal("43.67")

    # change > 0 without exactly one cash row: unreadable
    card_and_change = response(
        total="43,67",
        payments=[payment(CARD, "50,00"), payment(CHANGE, "6,33")],
    )
    with pytest.raises(UnreadableReceipt, match="without exactly one cash row"):
        PLUGINS["kaufland"].normalize(card_and_change)


def test_matrix_split_payment_and_unknown_payment() -> None:
    # Split payment: Kartica 4,99, Euro EUR 10,00, Za vratiti 0,00 -> card 4.99, cash 10.00
    raw = response(
        total="14,99",
        payments=[
            payment(CARD, "4,99"),
            payment(CASH, "10,00"),
            payment(CHANGE, "0,00"),
        ],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert len(receipt.settlements) == 2
    assert receipt.settlements[0].kind == SettlementKind.CARD
    assert receipt.settlements[0].amount == Decimal("4.99")
    assert receipt.settlements[1].kind == SettlementKind.CASH
    assert receipt.settlements[1].amount == Decimal("10.00")

    # unknown payment label, including Lidl's cash wording: unreadable
    for label in ("BON", "Gotovina"):
        unknown = response(total="4,99", payments=[payment(label, "4,99")])
        with pytest.raises(UnreadableReceipt, match="not a known kind"):
            PLUGINS["kaufland"].normalize(unknown)


@pytest.mark.parametrize(
    "lines",
    [
        [item("K.Voda 7L", "1", None, "1,45"), discount("amb.- staklo *", "0,00")],
        [item("K.Voda 7L", "0", None, "1,45")],
    ],
    ids=["zero-deposit", "zero-quantity"],
)
def test_line_model_errors_are_unreadable(lines: list[Any]) -> None:
    # A raw ValidationError would carry receipt content into the error log.
    raw = response(lines=lines, total="1,45", payments=[payment(CARD, "1,45")])
    with pytest.raises(UnreadableReceipt, match="fails the model"):
        PLUGINS["kaufland"].normalize(raw)


def test_matrix_branch_mismatch() -> None:
    # Branch mismatch: PJ5230, Račun 21833/4430/6 -> unreadable
    mismatch = response(
        pj_line="PJ5230,Zagreb Blato",
        receipt_number="21833/4430/6",
    )
    with pytest.raises(UnreadableReceipt, match="disagrees with receipt number"):
        PLUGINS["kaufland"].normalize(mismatch)

    # Valid branch matching middle segment
    valid = response(
        pj_line="PJ5230,Zagreb Blato",
        receipt_number="21833/5230/6",
    )
    receipt = PLUGINS["kaufland"].normalize(valid)
    assert receipt.branch_number == "5230"
    assert receipt.store_name == "Zagreb Blato"


def test_matrix_fiscal_time() -> None:
    # Fiscal time: Datum:25.02.26 Vrijeme12:33:51 -> 2026-02-25 12:33 Zagreb -> 11:33 UTC
    raw = response(purchase_date="25.02.26", purchase_time="12:33:51")
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert receipt.purchased_at == datetime(2026, 2, 25, 11, 33, tzinfo=UTC)

    # Unreadable date or time: unreadable
    with pytest.raises(UnreadableReceipt, match="cannot be read"):
        PLUGINS["kaufland"].normalize(response(purchase_date="invalid"))
    with pytest.raises(UnreadableReceipt, match="cannot be read"):
        PLUGINS["kaufland"].normalize(response(purchase_time="invalid"))


def test_matrix_info_rows_dropped() -> None:
    # Međusuma, Suma, Povratna naknada, a … HRK conversion row, the PDV table,
    # Kaufland Card: line and * bez prava na popust never enter lines or settlements.
    raw = response(
        lines=[
            item("K.Voda 7L", "1", None, "1,45"),
            discount("Međusuma", "1,45"),
            discount("Suma", "1,45"),
            discount("Povratna naknada", "0,10"),
            discount("1 EUR = 7,53450 HRK", "10,93"),
            discount("PDV 25%", "0,29"),
            discount("Kaufland Card: xxxxx8265", "0,00"),
            discount("* bez prava na popust", "0,00"),
        ],
        total="1,45",
        payments=[
            payment(CARD, "1,45"),
            payment("Međusuma", "1,45"),
            payment("Suma", "1,45"),
            payment("Povratna naknada", "0,10"),
            payment("PDV", "0,29"),
            payment("1 EUR = 7,53450 HRK", "10,93"),
        ],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert len(receipt.lines) == 1
    assert receipt.lines[0].printed_text == "K.Voda 7L"
    assert len(receipt.settlements) == 1
    assert receipt.settlements[0].kind == SettlementKind.CARD
    assert receipt.settlements[0].amount == Decimal("1.45")


def test_matrix_returned_beer_bottle() -> None:
    # Returned beer bottles: Boca za pivo * 4 * 0,16 -0,64 -> deposit_refund of 0.64 EUR
    # Bought beer bottle: Boca za pivo * 1 * 0,16 0,16 -> sale line (qty 1, price 0.16, amount 0.16)
    raw = response(
        lines=[
            item("Boca za pivo *", "1", "0,16", "0,16"),
            item("Boca za pivo *", "4", "0,16", "-0,64"),
        ],
        total="-0,48",
        payments=[payment(CARD, "-0,48")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert receipt.total == Decimal("0.16")
    assert len(receipt.lines) == 1
    assert receipt.lines[0].printed_text == "Boca za pivo *"
    assert receipt.lines[0].quantity == Decimal(1)
    assert receipt.lines[0].unit_price == Decimal("0.16")
    assert receipt.lines[0].printed_amount == Decimal("0.16")
    assert len(receipt.settlements) == 2
    assert receipt.settlements[0].kind == SettlementKind.CARD
    assert receipt.settlements[0].amount == Decimal("-0.48")
    assert receipt.settlements[1].kind == SettlementKind.DEPOSIT_REFUND
    assert receipt.settlements[1].amount == Decimal("0.64")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_mixed_deposit_refunds() -> None:
    # Mixed deposit refunds: amb.- staklo -0.20, ambalaža - PET -0.40, Boca za pivo -0.64
    # -> three deposit_refund settlements summing to 1.24 EUR
    raw = response(
        lines=[
            item("Kruh njemački", "1", None, "2,00"),
            discount("amb.- staklo", "-0,20"),
            discount("ambalaža - PET", "-0,40"),
            item("Boca za pivo", "4", "0,16", "-0,64"),
        ],
        total="0,76",
        payments=[payment(CARD, "0,76")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert receipt.total == Decimal("2.00")
    assert len(receipt.lines) == 1
    deposit_refunds = [s for s in receipt.settlements if s.kind == SettlementKind.DEPOSIT_REFUND]
    assert len(deposit_refunds) == 3
    assert [s.amount for s in deposit_refunds] == [
        Decimal("0.20"),
        Decimal("0.40"),
        Decimal("0.64"),
    ]
    assert sum(s.amount for s in deposit_refunds) == Decimal("1.24")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_standard_deposit_with_quantity() -> None:
    # Standard deposit row: ambalaža - PET * 14 * 0,10 -1,40 -> deposit_refund of 1.40 EUR
    raw = response(
        lines=[
            item("K.Voda 7L", "2", "1,45", "2,90"),
            item("ambalaža - PET * 14 * 0,10", "14", "0,10", "-1,40"),
        ],
        total="1,50",
        payments=[payment(CARD, "1,50")],
    )
    receipt = PLUGINS["kaufland"].normalize(raw)
    assert receipt.total == Decimal("2.90")
    assert len(receipt.lines) == 1
    deposit_refunds = [s for s in receipt.settlements if s.kind == SettlementKind.DEPOSIT_REFUND]
    assert len(deposit_refunds) == 1
    assert deposit_refunds[0].amount == Decimal("1.40")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_unknown_negative_item_with_quantity() -> None:
    # Unknown negative item with qty: Nepoznati artikl * 2 * 1,00 -2,00 -> unreadable naming row
    raw = response(lines=[item("Nepoznati artikl", "2", "1,00", "-2,00")])
    with pytest.raises(UnreadableReceipt, match="Nepoznati artikl"):
        PLUGINS["kaufland"].normalize(raw)


def test_sample_20260427_231253_with_returned_bottles() -> None:
    # Sample 20260427_231253: 18 goods lines (62.47), 3 refunds (1.24), Card 61.23
    receipt = PLUGINS["kaufland"].normalize(SAMPLE_20260427_231253_PASS2)
    assert len(receipt.lines) == 18
    assert sum(line.effective_amount for line in receipt.lines) == Decimal("62.47")
    assert receipt.total == Decimal("62.47")
    assert sum(s.amount for s in receipt.settlements) == Decimal("62.47")
    deposit_refunds = [s for s in receipt.settlements if s.kind == SettlementKind.DEPOSIT_REFUND]
    assert len(deposit_refunds) == 3
    assert [s.amount for s in deposit_refunds] == [
        Decimal("0.20"),
        Decimal("0.40"),
        Decimal("0.64"),
    ]
    assert sum(s.amount for s in deposit_refunds) == Decimal("1.24")
    card_settlements = [s for s in receipt.settlements if s.kind == SettlementKind.CARD]
    assert len(card_settlements) == 1
    assert card_settlements[0].amount == Decimal("61.23")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None
