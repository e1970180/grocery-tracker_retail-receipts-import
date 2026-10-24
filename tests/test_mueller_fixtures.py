"""Recorded Müller responses against their hand-derived records, offline."""

import functools
import io
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pydantic import BaseModel

from retail_receipts_import.adapters.gemini import images
from retail_receipts_import.adapters.postgres.chains import ChainReference
from retail_receipts_import.adapters.postgres.receipts import WriteKind, WriteResult
from retail_receipts_import.app.pipeline import Ports, Stored
from retail_receipts_import.domain.chains import KnownChain
from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.mueller.schema import MuellerPass2
from retail_receipts_import.domain.chains.pass1 import Pass1Response
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
from tests.mueller_samples import (
    BONUS,
    CARD,
    CASH,
    CHANGE,
    MUELLER_OIB,
    item,
    payment,
    response,
)
from tests.steps import run_steps

FIXTURES = Path(__file__).parent / "fixtures"
MUELLER_FIXTURES = FIXTURES / "mueller"

CASE_FOLDERS = sorted(p for p in MUELLER_FIXTURES.iterdir() if p.is_dir())


def _recorded(name: str) -> NormalizedReceipt:
    return PLUGINS["mueller"].normalize(
        (MUELLER_FIXTURES / name / "pass2.json").read_text(encoding="utf-8")
    )


def test_all_recorded_cases_are_present() -> None:
    # A lost folder would otherwise just shrink the parametrized tests below.
    assert len(CASE_FOLDERS) == 15


@pytest.mark.parametrize("case", CASE_FOLDERS, ids=[case.name for case in CASE_FOLDERS])
def test_recorded_response_gives_the_confirmed_record(case: Path) -> None:
    receipt = _recorded(case.name)
    expected = NormalizedReceipt.model_validate_json(
        (case / "expected.json").read_text(encoding="utf-8")
    )
    assert receipt == expected
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


@pytest.mark.parametrize("case", [c for c in CASE_FOLDERS if "-" in c.name], ids=lambda c: c.name)
def test_copies_of_one_receipt_give_one_record(case: Path) -> None:
    # Two photos of one receipt must meet in the dedup key, so they must give the same record.
    assert _recorded(case.name) == _recorded(case.name.split("-")[0])


def test_recorded_bonus_and_deposit() -> None:
    receipt = _recorded("76391")
    assert ("POVRATNA NAKNADA", Decimal("0.10")) in [
        (line.printed_text, line.printed_amount) for line in receipt.lines
    ]
    assert [(s.kind, s.amount) for s in receipt.settlements] == [
        (SettlementKind.BONUS_POINTS, Decimal("3.01")),
        (SettlementKind.CARD, Decimal("3.28")),
    ]
    assert receipt.total == Decimal("6.29")


def test_recorded_discount() -> None:
    receipt = _recorded("74630")
    line = receipt.lines[0]
    assert line.printed_text == "BLINK SPUŽVASTA KRP"
    assert (line.unit_price, line.printed_amount, line.included_discount) == (
        Decimal("0.99"),
        Decimal("0.89"),
        Decimal("0.10"),
    )
    assert line.discount_text == "Coupon 0,89 Blink"
    assert receipt.total == Decimal("20.88")


@pytest.mark.parametrize("case", CASE_FOLDERS, ids=[case.name for case in CASE_FOLDERS])
def test_pipeline_stores_recorded_mueller_samples(case: Path, tmp_path: Path) -> None:
    pass2_text = (case / "pass2.json").read_text(encoding="utf-8")
    pass1_text = (case / "pass1.json").read_text(encoding="utf-8")
    expected = NormalizedReceipt.model_validate_json(
        (case / "expected.json").read_text(encoding="utf-8")
    )

    # A pass 1 that read the card slip instead of the footer would put the dedup check a
    # minute off on two of these receipts.
    p1_obj = Pass1Response.model_validate_json(pass1_text)
    p1_time = PLUGINS["mueller"].normalize_pass1_time(
        p1_obj.purchase_date or "", p1_obj.purchase_time or ""
    )
    assert p1_time == expected.purchased_at

    png_path = tmp_path / f"{case.name}.png"
    img_buf = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(img_buf, format="PNG")
    png_path.write_bytes(img_buf.getvalue())
    stored_id = uuid.uuid7()
    written_receipts: list[NormalizedReceipt] = []

    def fake_generate(data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        if schema is MuellerPass2:
            return pass2_text
        return pass1_text

    def fake_write(
        receipt_id: uuid.UUID, receipt: NormalizedReceipt, source: ReceiptSource
    ) -> WriteResult:
        written_receipts.append(receipt)
        return WriteResult(WriteKind.STORED, stored_id)

    reference = ChainReference(
        chains=(
            KnownChain("mueller", "Müller", ("MÜLLER", "Müller", "Muller"), (MUELLER_OIB,)),
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
    result = run_steps(png_path, "image/png", telegram_source(0, 1, buyer_name="tester"), ports)
    assert result == Stored(stored_id)
    assert written_receipts == [expected]
    assert written_receipts[0].chain_id == "mueller"


def test_mueller_plugin_pass1_time_normalizer() -> None:
    mueller = PLUGINS["mueller"]
    # Zagreb daylight saving time (CEST is UTC+2): 10:15 local -> 08:15 UTC.
    assert mueller.normalize_pass1_time("18.05.2025", "10:15") == datetime(
        2025, 5, 18, 8, 15, tzinfo=UTC
    )
    assert mueller.normalize_pass1_time("18.05.2025.", "10:15") == datetime(
        2025, 5, 18, 8, 15, tzinfo=UTC
    )
    # Zagreb winter time (CET is UTC+1): 19:17 local -> 18:17 UTC.
    assert mueller.normalize_pass1_time("15.03.2025", "19:17") == datetime(
        2025, 3, 15, 18, 17, tzinfo=UTC
    )
    # The card slip's time carries seconds and may be a minute later than the footer.
    assert mueller.normalize_pass1_time("15.03.2025", "19:18:09") is None
    assert mueller.normalize_pass1_time("15.03.25", "19:17") is None
    # Unreadable or invalid dates/times return None and never raise.
    assert mueller.normalize_pass1_time("invalid", "19:17") is None
    assert mueller.normalize_pass1_time("15.03.2025", "invalid") is None
    assert mueller.normalize_pass1_time("32.13.2025", "19:17") is None
    assert mueller.normalize_pass1_time("", "") is None


def test_mueller_plugin_seller_oib() -> None:
    mueller = PLUGINS["mueller"]
    assert mueller.seller_oib(response()) == MUELLER_OIB
    assert mueller.seller_oib(response(seller_oib=f" {MUELLER_OIB} ")) == MUELLER_OIB
    assert mueller.seller_oib(response(seller_oib=None)) is None
    assert mueller.seller_oib(response(seller_oib="  ")) is None
    assert mueller.seller_oib("not json") is None


def _property_names(schema: Any) -> list[str]:
    if isinstance(schema, dict):
        own = list(schema.get("properties", {}))
        return own + [name for value in schema.values() for name in _property_names(value)]
    if isinstance(schema, list):
        return [name for value in schema for name in _property_names(value)]
    return []


def test_mueller_schema_asks_for_no_slip_or_terminal_field() -> None:
    names = _property_names(MuellerPass2.model_json_schema())
    assert "payments" in names
    for name in names:
        assert not re.search(r"card|pan|tid|mid|rrn|terminal|chain", name, re.IGNORECASE), name


def test_matrix_bonus_and_deposit() -> None:
    # Bonus + deposit: lines 1,39 / 3,85 / 0,95 / POVRATNA NAKNADA * 0,10b,
    # Müller bodovi EUR 3,01, ZA PLATITI 3,28, card 3,28
    # -> 4 lines (deposit POVRATNA NAKNADA 0.10), bonus 3.01 + card 3.28, total 6.29
    raw = response(
        lines=[
            item("ITEM 1", "1", "1,39", "1,39a"),
            item("ITEM 2", "1", "3,85", "3,85a"),
            item("ITEM 3", "1", "0,95", "0,95a"),
            item("POVRATNA NAKNADA *", None, "0,10", "0,10b"),
        ],
        amount_to_pay="3,28",
        payments=[
            payment(BONUS, "3,01"),
            payment(CARD, "3,28"),
        ],
    )
    receipt = PLUGINS["mueller"].normalize(raw)
    assert len(receipt.lines) == 4
    deposit_line = receipt.lines[3]
    assert deposit_line.printed_text == "POVRATNA NAKNADA"
    assert deposit_line.quantity == Decimal(1)
    assert deposit_line.unit_price == Decimal("0.10")
    assert deposit_line.printed_amount == Decimal("0.10")
    assert deposit_line.included_discount == Decimal(0)

    assert len(receipt.settlements) == 2
    assert receipt.settlements[0].kind == SettlementKind.BONUS_POINTS
    assert receipt.settlements[0].amount == Decimal("3.01")
    assert receipt.settlements[1].kind == SettlementKind.CARD
    assert receipt.settlements[1].amount == Decimal("3.28")

    assert receipt.total == Decimal("6.29")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_discount() -> None:
    # Discount: 1 BLINK SPUŽVASTA KRP 0,99 -0,10 0,89a, Coupon 0,89 Blink
    # -> unit 0.99, printed 0.89, included 0.10, discount_text Coupon 0,89 Blink
    raw = response(
        lines=[
            item(
                "BLINK SPUŽVASTA KRP",
                "1",
                "0,99",
                "0,89a",
                discount="-0,10",
                discount_note="Coupon 0,89 Blink",
            )
        ],
        amount_to_pay="0,89",
        payments=[payment(CARD, "0,89")],
    )
    receipt = PLUGINS["mueller"].normalize(raw)
    assert len(receipt.lines) == 1
    line = receipt.lines[0]
    assert line.printed_text == "BLINK SPUŽVASTA KRP"
    assert line.quantity == Decimal(1)
    assert line.unit_price == Decimal("0.99")
    assert line.printed_amount == Decimal("0.89")
    assert line.included_discount == Decimal("0.10")
    assert line.discount_text == "Coupon 0,89 Blink"
    assert receipt.total == Decimal("0.89")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_discount_equation_mismatch() -> None:
    # Kom x Cijena + Popust != Iznos: unreadable
    raw = response(
        lines=[
            item("BLINK SPUŽVASTA KRP", "1", "0,99", "0,88a", discount="-0,10"),
        ],
        amount_to_pay="0,88",
        payments=[payment(CARD, "0,88")],
    )
    with pytest.raises(UnreadableReceipt, match="fails Kom x Cijena \\+ Popust = Iznos"):
        PLUGINS["mueller"].normalize(raw)


def test_matrix_positive_discount_fails() -> None:
    # Non-negative discount fails row rule: unreadable
    raw = response(
        lines=[
            item("BLINK SPUŽVASTA KRP", "1", "0,99", "0,89a", discount="0,10"),
        ],
        amount_to_pay="0,89",
        payments=[payment(CARD, "0,89")],
    )
    with pytest.raises(UnreadableReceipt, match="discount '0,10' is not negative"):
        PLUGINS["mueller"].normalize(raw)


def test_matrix_cash_with_change() -> None:
    # Cash with change: GOTOVINA 50,00, POVRAT NOVCA -34,40 -> cash 15.60
    raw = response(
        lines=[item("ITEM", "1", "15,60", "15,60a")],
        amount_to_pay="15,60",
        payments=[payment(CASH, "50,00"), payment(CHANGE, "-34,40")],
    )
    receipt = PLUGINS["mueller"].normalize(raw)
    assert len(receipt.settlements) == 1
    assert receipt.settlements[0].kind == SettlementKind.CASH
    assert receipt.settlements[0].amount == Decimal("15.60")
    assert receipt.total == Decimal("15.60")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_matrix_change_without_cash_row() -> None:
    # Change without exactly one cash row: unreadable
    raw = response(
        lines=[item("ITEM", "1", "15,60", "15,60a")],
        amount_to_pay="15,60",
        payments=[payment(CARD, "50,00"), payment(CHANGE, "-34,40")],
    )
    with pytest.raises(UnreadableReceipt, match="without exactly one cash row"):
        PLUGINS["mueller"].normalize(raw)


def test_matrix_footer_time() -> None:
    # Footer time: 15.03.2025 19:17 -> 2025-03-15 19:17 Zagreb -> UTC 18:17
    raw = response(purchase_date="15.03.2025", purchase_time="19:17")
    receipt = PLUGINS["mueller"].normalize(raw)
    assert receipt.purchased_at == datetime(2025, 3, 15, 18, 17, tzinfo=UTC)

    # Unreadable date or time: unreadable
    with pytest.raises(UnreadableReceipt, match="cannot be read"):
        PLUGINS["mueller"].normalize(response(purchase_date="invalid"))
    with pytest.raises(UnreadableReceipt, match="cannot be read"):
        PLUGINS["mueller"].normalize(response(purchase_time="invalid"))
    # The card slip's VRIJEME, copied by mistake, is refused rather than stored a minute off.
    with pytest.raises(UnreadableReceipt, match="cannot be read"):
        PLUGINS["mueller"].normalize(response(purchase_time="19:18:09"))


def test_matrix_branch_and_receipt_number() -> None:
    # Branch: RB :143667/4972/4 -> branch 4972, receipt_number 143667/4972/4
    raw = response(receipt_number="RB :143667/4972/4")
    receipt = PLUGINS["mueller"].normalize(raw)
    assert receipt.branch_number == "4972"
    assert receipt.receipt_number == "143667/4972/4"

    # Fewer than three segments: unreadable
    raw_two_seg = response(receipt_number="RB :143667/4972")
    with pytest.raises(UnreadableReceipt, match="fewer than three segments"):
        PLUGINS["mueller"].normalize(raw_two_seg)

    # Missing receipt number: unreadable
    raw_none = response(receipt_number=None)
    with pytest.raises(UnreadableReceipt, match="missing receipt number"):
        PLUGINS["mueller"].normalize(raw_none)


def test_matrix_deposit_without_price_match() -> None:
    # Deposit without price match: no Kom, Cijena 0,10, Iznos 0,20 -> unreadable
    raw = response(
        lines=[item("POVRATNA NAKNADA", None, "0,10", "0,20b")],
        amount_to_pay="0,20",
        payments=[payment(CARD, "0,20")],
    )
    with pytest.raises(UnreadableReceipt, match="fails Kom x Cijena \\+ Popust = Iznos"):
        PLUGINS["mueller"].normalize(raw)


def test_matrix_missing_quantity_on_non_deposit() -> None:
    # Missing quantity: item other than POVRATNA NAKNADA without Kom -> unreadable
    raw = response(
        lines=[item("BLINK SPUŽVA", None, "1,00", "1,00a")],
        amount_to_pay="1,00",
        payments=[payment(CARD, "1,00")],
    )
    with pytest.raises(UnreadableReceipt, match="lacks quantity"):
        PLUGINS["mueller"].normalize(raw)


def test_matrix_unknown_payment() -> None:
    # Unknown payment: AMEX EUR 3,00 -> unreadable
    raw = response(payments=[payment("AMEX EUR", "3,00")])
    with pytest.raises(UnreadableReceipt, match="not a known kind"):
        PLUGINS["mueller"].normalize(raw)


def test_matrix_negative_item() -> None:
    # Negative item: item Iznos -1,00 -> unreadable
    raw = response(lines=[item("BLINK SPUŽVA", "1", "1,00", "-1,00a")])
    with pytest.raises(UnreadableReceipt, match="is not a printed amount|not positive"):
        PLUGINS["mueller"].normalize(raw)


def test_matrix_text_cleaning() -> None:
    # Trailing standalone ' *' dropped, inner '*' preserved, whitespace runs collapsed
    raw = response(
        lines=[
            item("BARFUSS UREA*BD KRE *", "1", "2,50", "2,50a"),
            item("DOUBLE   SPACE    TEXT", "1", "1,00", "1,00a"),
        ],
        amount_to_pay="3,50",
        payments=[payment(CARD, "3,50")],
    )
    receipt = PLUGINS["mueller"].normalize(raw)
    assert len(receipt.lines) == 2
    assert receipt.lines[0].printed_text == "BARFUSS UREA*BD KRE"
    assert receipt.lines[1].printed_text == "DOUBLE SPACE TEXT"


def test_matrix_subtotals_and_info_rows_dropped() -> None:
    # Međuzbroj and PDV rows dropped, real lines stay
    raw = response(
        lines=[
            item("REAL ITEM 1", "1", "1,00", "1,00a"),
            item("MEĐUZBROJ", "1", "1,00", "1,00a"),
            item("MEDUZBROJ", "1", "1,00", "1,00a"),
            item("PDV 25%", "1", "0,00", "0,00a"),
            item("** Ponovni ispis računa **", "1", "0,00", "0,00a"),
            item("REAL ITEM 2", "1", "2,00", "2,00a"),
        ],
        amount_to_pay="3,00",
        payments=[payment(CARD, "3,00")],
    )
    receipt = PLUGINS["mueller"].normalize(raw)
    assert [line.printed_text for line in receipt.lines] == ["REAL ITEM 1", "REAL ITEM 2"]


def test_matrix_store_name_and_address() -> None:
    # Specific shop address and name preserved, company head office line and phone stripped
    raw = response(
        store_name="Zagreb EKZ Arena",
        store_address=(
            "Ulica Vice Vukova 6, 10000 Zagreb\nOreškovićeva 6H/1, 10 020 Zagreb, Tel: 01 2345678"
        ),
    )
    receipt = PLUGINS["mueller"].normalize(raw)
    assert receipt.store_name == "Zagreb EKZ Arena"
    assert receipt.store_address == "Ulica Vice Vukova 6, 10000 Zagreb"

    # Head office as store name filtered out
    raw_company_store = response(store_name="MÜLLER TRGOVINA ZAGREB D.O.O.")
    receipt_company = PLUGINS["mueller"].normalize(raw_company_store)
    assert receipt_company.store_name is None
