"""Recorded Lidl responses against their hand-derived records, offline."""

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
from retail_receipts_import.domain.chains.lidl.schema import LidlPass2
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
from tests.lidl_samples import CARD, CASH, CHANGE, discount, item, payment, response
from tests.steps import run_steps

FIXTURES = Path(__file__).parent / "fixtures"
CASES = sorted(
    path.parent
    for path in (FIXTURES / "lidl").glob("*/pass2.json")
    if (path.parent / "expected.json").is_file()
)


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_recorded_response_gives_the_confirmed_record(case: Path) -> None:
    receipt = PLUGINS["lidl"].normalize((case / "pass2.json").read_text(encoding="utf-8"))
    expected = NormalizedReceipt.model_validate_json(
        (case / "expected.json").read_text(encoding="utf-8")
    )
    assert receipt == expected
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_pipeline_stores_recorded_lidl_samples(case: Path, tmp_path: Path) -> None:
    pass2_text = (case / "pass2.json").read_text(encoding="utf-8")
    pass1_text = (case / "pass1.json").read_text(encoding="utf-8")
    png_path = tmp_path / f"{case.name}.png"
    img_buf = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(img_buf, format="PNG")
    png_path.write_bytes(img_buf.getvalue())
    stored_id = uuid.uuid7()
    written_receipts: list[NormalizedReceipt] = []

    def fake_generate(data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        if schema is LidlPass2:
            return pass2_text
        return pass1_text

    def fake_write(
        receipt_id: uuid.UUID, receipt: NormalizedReceipt, source: ReceiptSource
    ) -> WriteResult:
        written_receipts.append(receipt)
        return WriteResult(WriteKind.STORED, stored_id)

    reference = ChainReference(
        chains=(
            KnownChain("lidl", "Lidl", ("LIDL", "Lidl"), ("66089976432",)),
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
    expected = NormalizedReceipt.model_validate_json(
        (case / "expected.json").read_text(encoding="utf-8")
    )
    assert written_receipts == [expected]
    assert written_receipts[0].chain_id == "lidl"


def test_lidl_plugin_pass1_time_normalizer() -> None:
    lidl = PLUGINS["lidl"]
    # Zagreb daylight saving time (CEST is UTC+2): 15:54 local -> 13:54 UTC.
    assert lidl.normalize_pass1_time("23.05.2026", "15:54:37") == datetime(
        2026, 5, 23, 13, 54, tzinfo=UTC
    )
    assert lidl.normalize_pass1_time("23.05.2026.", "15:54") == datetime(
        2026, 5, 23, 13, 54, tzinfo=UTC
    )
    # Zagreb winter time (CET is UTC+1): 14:31 local -> 13:31 UTC.
    assert lidl.normalize_pass1_time("11.02.2025", "14:31:24") == datetime(
        2025, 2, 11, 13, 31, tzinfo=UTC
    )
    assert lidl.normalize_pass1_time("11.02.2025.", "14:31") == datetime(
        2025, 2, 11, 13, 31, tzinfo=UTC
    )
    # Unreadable or invalid dates/times return None and never raise.
    assert lidl.normalize_pass1_time("invalid", "15:54:37") is None
    assert lidl.normalize_pass1_time("23.05.2026", "invalid") is None
    assert lidl.normalize_pass1_time("32.13.2030", "09:05:00") is None
    assert lidl.normalize_pass1_time("", "") is None


def test_lidl_plugin_seller_oib() -> None:
    lidl = PLUGINS["lidl"]
    assert lidl.seller_oib(response()) == "66089976432"
    assert lidl.seller_oib(response(seller_oib=" 66089976432 ")) == "66089976432"
    assert lidl.seller_oib(response(seller_oib=None)) is None
    assert lidl.seller_oib(response(seller_oib="  ")) is None
    assert lidl.seller_oib("not json") is None


def _property_names(schema: Any) -> list[str]:
    if isinstance(schema, dict):
        own = list(schema.get("properties", {}))
        return own + [name for value in schema.values() for name in _property_names(value)]
    if isinstance(schema, list):
        return [name for value in schema for name in _property_names(value)]
    return []


def test_lidl_schema_asks_for_no_card_or_terminal_field() -> None:
    names = _property_names(LidlPass2.model_json_schema())
    assert "payments" in names
    for name in names:
        assert not re.search(r"card|pan|tid|mid|rrn|terminal|chain", name), name


def test_matrix_item_discount() -> None:
    # Item discount: 1 Kremšnita 3,29 then POPUST 25% -0,83 -> one line, printed 3.29,
    # separate_discount 0.83, discount_text POPUST 25%
    raw = response(
        lines=[item("1 Kremšnita", "1", None, "3,29"), discount("POPUST 25%", "-0,83")],
        total="2,46",
        payments=[payment(CARD, "2,46")],
    )
    receipt = PLUGINS["lidl"].normalize(raw)
    assert len(receipt.lines) == 1
    line = receipt.lines[0]
    assert line.printed_text == "Kremšnita"
    assert line.quantity == Decimal(1)
    assert line.printed_amount == Decimal("3.29")
    assert line.separate_discount == Decimal("0.83")
    assert line.discount_text == "POPUST 25%"


@pytest.mark.parametrize("footer", ["POPUST", "POPUST "])
def test_matrix_footer_trap(footer: str) -> None:
    # Footer trap: footer POPUST 0,83 printed; model lists it in lines or payments anyway -> dropped
    raw = response(
        lines=[
            item("1 Kremšnita", "1", None, "3,29"),
            discount(footer, "-0,83"),
        ],
        total="3,29",
        payments=[
            payment(CARD, "3,29"),
            payment(footer, "0,83"),
        ],
    )
    receipt = PLUGINS["lidl"].normalize(raw)
    assert len(receipt.lines) == 1
    assert receipt.lines[0].separate_discount == Decimal(0)
    assert len(receipt.settlements) == 1
    assert receipt.settlements[0].kind == SettlementKind.CARD


def test_matrix_single_item() -> None:
    # Single item: 1 Kremšnita 3,29 C -> text Kremšnita, quantity 1
    raw = response(
        lines=[item("1 Kremšnita", "1", None, "3,29")],
        total="3,29",
        payments=[payment(CARD, "3,29")],
    )
    receipt = PLUGINS["lidl"].normalize(raw)
    assert receipt.lines[0].printed_text == "Kremšnita"
    assert receipt.lines[0].quantity == Decimal(1)
    assert receipt.lines[0].printed_amount == Decimal("3.29")
    assert receipt.lines[0].unit_price is None


def test_matrix_weighed_item() -> None:
    # Weighed item: Šljiva okrugla 3,77 with 0,946 kg x 3,99 EUR/kg under it
    raw = response(
        lines=[item("Šljiva okrugla", "0,946", "3,99", "3,77", unit="kg")],
        total="3,77",
        payments=[payment(CARD, "3,77")],
    )
    receipt = PLUGINS["lidl"].normalize(raw)
    assert receipt.lines[0].printed_text == "Šljiva okrugla"
    assert receipt.lines[0].quantity == Decimal("0.946")
    assert receipt.lines[0].unit == "kg"
    assert receipt.lines[0].unit_price == Decimal("3.99")
    assert receipt.lines[0].printed_amount == Decimal("3.77")


def test_matrix_cash_with_change() -> None:
    # Cash with change: Novčanice 100,00, Ostatak novčanice -57,03 -> one cash settlement 42.97
    raw = response(
        total="42,97",
        payments=[payment(CASH, "100,00"), payment(CHANGE, "-57,03")],
    )
    receipt = PLUGINS["lidl"].normalize(raw)
    assert len(receipt.settlements) == 1
    assert receipt.settlements[0].kind == SettlementKind.CASH
    assert receipt.settlements[0].amount == Decimal("42.97")

    # change without one cash row is unreadable
    card_and_change = response(
        total="42,97",
        payments=[payment(CARD, "100,00"), payment(CHANGE, "-57,03")],
    )
    with pytest.raises(UnreadableReceipt, match="without exactly one cash row"):
        PLUGINS["lidl"].normalize(card_and_change)


def test_matrix_deposit_return() -> None:
    # Deposit return: Otkup ambalaže -3,60 D among the items -> deposit_refund settlement 3.60
    raw = response(
        lines=[
            item("Kremšnita", "1", None, "5,59"),
            discount("Otkup ambalaže", "-3,60"),
        ],
        total="1,99",
        payments=[payment(CARD, "1,99")],
    )
    receipt = PLUGINS["lidl"].normalize(raw)
    assert receipt.total == Decimal("5.59")
    assert len(receipt.lines) == 1
    assert receipt.lines[0].printed_text == "Kremšnita"
    assert len(receipt.settlements) == 2
    assert receipt.settlements[0] == (
        receipt.settlements[0].model_copy(
            update={"kind": SettlementKind.CARD, "amount": Decimal("1.99")}
        )
    )
    deposit_settlement = receipt.settlements[1]
    assert deposit_settlement.kind == SettlementKind.DEPOSIT_REFUND
    assert deposit_settlement.amount == Decimal("3.60")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_deposit_return_among_payments_counts_in_the_total() -> None:
    # The model may list Otkup ambalaže under payments; it is still outside za platiti.
    raw = response(
        lines=[item("Kremšnita", "1", None, "5,59")],
        total="1,99",
        payments=[payment(CARD, "1,99"), payment("Otkup ambalaže", "-3,60")],
    )
    receipt = PLUGINS["lidl"].normalize(raw)
    assert receipt.total == Decimal("5.59")
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_lidl_misread_amount_to_pay_fails_check_total() -> None:
    # Lines and payments agree (2.00), but printed amount to pay is off by 0,01.
    raw = response(
        lines=[item("Kruh", "1", None, "2,00")],
        total="2,01",
        payments=[payment(CARD, "2,00")],
    )
    receipt = PLUGINS["lidl"].normalize(raw)
    assert check_consistency(receipt) is None
    assert check_total(receipt) == Decimal("0.01")


def test_matrix_price_change() -> None:
    # Price change: Promjena cijene 0,00 under an item -> dropped; non-zero: unreadable
    raw = response(
        lines=[
            item("Kremšnita", "1", None, "1,99"),
            discount("Promjena cijene", "0,00"),
        ],
        total="1,99",
        payments=[payment(CARD, "1,99")],
    )
    receipt = PLUGINS["lidl"].normalize(raw)
    assert len(receipt.lines) == 1

    nonzero_change = response(
        lines=[
            item("Kremšnita", "1", None, "1,99"),
            discount("Promjena cijene", "-0,10"),
        ],
        total="1,89",
        payments=[payment(CARD, "1,89")],
    )
    with pytest.raises(UnreadableReceipt, match="non-zero price change"):
        PLUGINS["lidl"].normalize(nonzero_change)


def test_matrix_branch() -> None:
    # Branch: PJ: 0269, falling back to IBR: 0269/024832/05 -> 0269
    receipt = PLUGINS["lidl"].normalize(response(pj="0269", ibr="0269/024832/05"))
    assert receipt.branch_number == "0269"

    # Fallback to IBR when PJ is missing
    receipt_fallback = PLUGINS["lidl"].normalize(response(pj=None, ibr="0198/038977/82"))
    assert receipt_fallback.branch_number == "0198"

    # Neither numeric -> unreadable
    with pytest.raises(UnreadableReceipt, match="gives a numeric branch"):
        PLUGINS["lidl"].normalize(response(pj=None, ibr="abc/def"))


def test_matrix_card_and_unknown_payment() -> None:
    # Card: Kartica 19,75 -> card settlement 19.75
    receipt = PLUGINS["lidl"].normalize(response(payments=[payment(CARD, "19,75")], total="19,75"))
    assert receipt.settlements[0].kind == SettlementKind.CARD
    assert receipt.settlements[0].amount == Decimal("19.75")

    # Unknown payment label is unreadable
    with pytest.raises(UnreadableReceipt, match="not a known kind"):
        PLUGINS["lidl"].normalize(response(payments=[payment("BON", "19,75")]))
