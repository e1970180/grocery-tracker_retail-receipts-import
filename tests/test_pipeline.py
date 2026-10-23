import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from retail_receipts_import.adapters.postgres.chains import ChainReference
from retail_receipts_import.adapters.postgres.receipts import WriteKind, WriteResult
from retail_receipts_import.app.pipeline import (
    Duplicate,
    Invalid,
    Ports,
    Result,
    Stored,
    Unsupported,
    process_file,
)
from retail_receipts_import.domain.chains import KnownChain
from retail_receipts_import.domain.chains.spar.prompt import PASS2_PROMPT
from retail_receipts_import.domain.chains.spar.schema import SparPass2
from retail_receipts_import.domain.outcomes import FailureReason
from retail_receipts_import.domain.receipt import (
    NormalizedReceipt,
    ReceiptSource,
    SettlementKind,
    telegram_source,
)
from tests.spar_samples import CARD, CASH, discount, item, pass1_response, payment, response

SOURCE = telegram_source(0, 1, buyer_name="tester")
STORED_ID = uuid.UUID(int=7)

DEFAULT_CHAINS = (
    KnownChain("dm", "dm", ("DM", "dm"), ("94124811986",)),
    KnownChain("kaufland", "Kaufland", ("KAUFLAND", "Kaufland"), ("47432874968",)),
    KnownChain("lidl", "Lidl", ("LIDL", "Lidl"), ("66089976432",)),
    KnownChain("mueller", "Müller", ("MÜLLER", "Müller", "Muller"), ("84698789700",)),
    KnownChain("spar", "Spar", ("SPAR", "Spar", "INTERSPAR"), ("46108893754",)),
)
DEFAULT_REFERENCE = ChainReference(
    chains=DEFAULT_CHAINS,
    inactive_ids=(),
    rejected=(),
)


@dataclass
class FakePorts:
    answers: list[str] = field(default_factory=list)
    answer: str = ""
    error: Exception | None = None
    reference: ChainReference = DEFAULT_REFERENCE
    write_kind: WriteKind = WriteKind.STORED
    calls: list[tuple[bytes, str, str, type[BaseModel]]] = field(default_factory=list)
    written: list[NormalizedReceipt] = field(default_factory=list)

    def generate(self, data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        self.calls.append((data, mime, prompt, schema))
        if self.error is not None:
            raise self.error
        if self.answers:
            return self.answers.pop(0)
        return self.answer

    def write(
        self, receipt_id: uuid.UUID, receipt: NormalizedReceipt, source: ReceiptSource
    ) -> WriteResult:
        self.written.append(receipt)
        return WriteResult(self.write_kind, STORED_ID)

    def read_chain_reference(self) -> ChainReference:
        return self.reference

    def ports(self) -> Ports:
        return Ports(
            generate=self.generate,
            write=self.write,
            read_chain_reference=self.read_chain_reference,
        )


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "receipt.pdf"
    path.write_bytes(b"%PDF-synthetic")
    return path


def run(pdf: Path, fake: FakePorts) -> Result:
    return process_file(pdf, "application/pdf", SOURCE, fake.ports())


def test_happy_path_stores_the_receipt(pdf: Path) -> None:
    fake = FakePorts(answers=[pass1_response(), response()])
    assert run(pdf, fake) == Stored(STORED_ID)
    assert len(fake.calls) == 2
    assert fake.calls[1][2] == PASS2_PROMPT
    assert fake.calls[1][3] is SparPass2
    [receipt] = fake.written
    assert receipt.chain_id == "spar"
    assert receipt.store_name == "SYNTHETIC STORE"
    assert receipt.branch_number == "2000"
    assert receipt.receipt_number == "100/2000/300"
    # 09:05 in Zagreb winter time is 08:05 UTC.
    assert receipt.purchased_at == datetime(2030, 2, 1, 8, 5, tzinfo=UTC)


def test_own_write_is_stored_and_duplicate_is_duplicate(pdf: Path) -> None:
    fake_own = FakePorts(answers=[pass1_response(), response()], write_kind=WriteKind.OWN_WRITE)
    assert run(pdf, fake_own) == Stored(STORED_ID)
    fake_dup = FakePorts(answers=[pass1_response(), response()], write_kind=WriteKind.DUPLICATE)
    assert run(pdf, fake_dup) == Duplicate(STORED_ID)


def test_joker_discount_is_the_item_above_it(pdf: Path) -> None:
    lines = [
        item("FIRST ITEM", "1", "1,80", "1,80"),
        item("JOKER ITEM", "1", "1,99", "1,99"),
        discount("Joker 15%", "-0,30"),
    ]
    fake = FakePorts(
        answers=[
            pass1_response(),
            response(lines=lines, total="3,49", payments=[payment(CARD, "3,49")]),
        ]
    )
    assert isinstance(run(pdf, fake), Stored)
    first, joker = fake.written[0].lines
    assert first.effective_amount == Decimal("1.80")
    assert joker.regular_amount == Decimal("1.99")
    assert joker.effective_amount == Decimal("1.69")
    assert joker.discount_text == "Joker 15%"


def test_savings_row_is_ignored_wherever_it_lands(pdf: Path) -> None:
    lines = [
        item("JOKER ITEM", "1", "1,99", "1,99"),
        discount("Joker 15%", "-0,30"),
        discount("Vaša ušteda: 0,30 EUR", "0,30"),
    ]
    payments = [payment(CARD, "1,69"), payment("Vasa usteda", "0,30")]
    fake = FakePorts(
        answers=[pass1_response(), response(lines=lines, total="1,69", payments=payments)]
    )
    assert isinstance(run(pdf, fake), Stored)
    receipt = fake.written[0]
    assert [line.effective_amount for line in receipt.lines] == [Decimal("1.69")]
    assert [s.amount for s in receipt.settlements] == [Decimal("1.69")]


def test_cash_with_change_is_one_cash_settlement_net_of_change(pdf: Path) -> None:
    payments = [payment(CASH, "50,00"), payment("OSTATAK NOVCA", "22,82")]
    lines = [item("CASH ITEM", "2", "13,59", "27,18")]
    fake = FakePorts(
        answers=[pass1_response(), response(lines=lines, total="27,18", payments=payments)]
    )
    assert isinstance(run(pdf, fake), Stored)
    [settlement] = fake.written[0].settlements
    assert settlement.kind is SettlementKind.CASH
    assert settlement.amount == Decimal("27.18")


def test_cash_and_card_are_two_settlements(pdf: Path) -> None:
    lines = [
        item("CHEESE", "1", "2,49", "2,49"),
        item("WHITE CHEESE", "1", "2,29", "2,29"),
        item("PORK", "0,430", "2,89", "1,24", unit="kg(N)"),
    ]
    payments = [payment(CASH, "1,89"), payment(CARD, "4,13")]
    fake = FakePorts(
        answers=[pass1_response(), response(lines=lines, total="6,02", payments=payments)]
    )
    assert isinstance(run(pdf, fake), Stored)
    receipt = fake.written[0]
    assert [(s.kind, s.amount) for s in receipt.settlements] == [
        (SettlementKind.CASH, Decimal("1.89")),
        (SettlementKind.CARD, Decimal("4.13")),
    ]
    weighed = receipt.lines[2]
    assert (weighed.quantity, weighed.unit, weighed.unit_price) == (
        Decimal("0.430"),
        "kg",
        Decimal("2.89"),
    )


def test_deposit_info_is_not_a_settlement(pdf: Path) -> None:
    # The deposit is already inside the bottle price; the model may still list its info row.
    payments = [payment(CARD, "5,94"), payment("Povratna naknada 6 * 0,10 = 0,60", "0,60")]
    lines = [item("WATER 1,5 L", "6", "0,99", "5,94")]
    fake = FakePorts(
        answers=[pass1_response(), response(lines=lines, total="5,94", payments=payments)]
    )
    assert isinstance(run(pdf, fake), Stored)
    [settlement] = fake.written[0].settlements
    assert (settlement.kind, settlement.amount) == (SettlementKind.CARD, Decimal("5.94"))


def test_chain_without_plugin_is_unsupported(pdf: Path) -> None:
    fake = FakePorts(answers=[pass1_response(chain="kaufland", store_name="KAUFLAND ZAGREB")])
    assert run(pdf, fake) == Unsupported("kaufland", "KAUFLAND ZAGREB")
    assert len(fake.calls) == 1
    assert fake.written == []


def test_other_chain_is_unsupported_with_store_name(pdf: Path) -> None:
    fake = FakePorts(answers=[pass1_response(chain="other", store_name="KONZUM D.D.")])
    assert run(pdf, fake) == Unsupported("other", "KONZUM D.D.")
    assert len(fake.calls) == 1
    assert fake.written == []


SPAR_WITHDRAWN = ChainReference(
    chains=tuple(chain for chain in DEFAULT_CHAINS if chain.chain_id != "spar"),
    inactive_ids=("spar",),
    rejected=(),
)


def test_inactive_chain_with_plugin_is_not_offered_and_not_extracted(pdf: Path) -> None:
    fake = FakePorts(
        answers=[pass1_response(chain="other", store_name="INTERSPAR ARENA")],
        reference=SPAR_WITHDRAWN,
    )
    assert run(pdf, fake) == Unsupported("other", "INTERSPAR ARENA")
    [(_, _, prompt, schema)] = fake.calls
    assert "spar" not in schema.model_json_schema()["properties"]["chain"]["enum"]
    assert "INTERSPAR" not in prompt
    assert fake.written == []


def test_inactive_chain_named_anyway_is_invalid_without_pass2(pdf: Path) -> None:
    fake = FakePorts(answers=[pass1_response(chain="spar")], reference=SPAR_WITHDRAWN)
    result = run(pdf, fake)
    assert isinstance(result, Invalid)
    assert result.reason is FailureReason.NO_VALID_RESULT
    assert len(fake.calls) == 1
    assert fake.written == []


def test_blank_store_name_is_none(pdf: Path) -> None:
    fake = FakePorts(answers=[pass1_response(chain="other", store_name="   ")])
    assert run(pdf, fake) == Unsupported("other", None)


def test_unreadable_chain_is_invalid(pdf: Path) -> None:
    fake = FakePorts(answers=[pass1_response(chain="unreadable")])
    result = run(pdf, fake)
    assert isinstance(result, Invalid)
    assert result.reason is FailureReason.NO_VALID_RESULT
    assert len(fake.calls) == 1
    assert fake.written == []


def test_pass1_unreadable_response_is_invalid(pdf: Path) -> None:
    fake = FakePorts(answers=["not json"])
    result = run(pdf, fake)
    assert isinstance(result, Invalid)
    assert result.reason is FailureReason.NO_VALID_RESULT
    assert len(fake.calls) == 1
    assert fake.written == []


def test_wrong_seller_oib_is_invalid_without_oib_in_detail(pdf: Path) -> None:
    fake = FakePorts(answers=[pass1_response(), response(seller_oib="99999999999")])
    result = run(pdf, fake)
    assert isinstance(result, Invalid)
    assert result.reason is FailureReason.NO_VALID_RESULT
    assert "99999999999" not in result.detail
    assert fake.written == []


def test_missing_seller_oib_is_invalid(pdf: Path) -> None:
    fake = FakePorts(answers=[pass1_response(), response(seller_oib=None)])
    result = run(pdf, fake)
    assert isinstance(result, Invalid)
    assert result.reason is FailureReason.NO_VALID_RESULT
    assert fake.written == []


@pytest.mark.parametrize(
    "answer",
    [
        response(purchase_date="32.13.2030."),
        response(purchase_date="1.2.2030"),
        response(purchase_time="9h05"),
        response(total="1.99"),
        response(lines=[item("ITEM", "1", "1,99", "1,99 A")]),
        response(lines=[discount("Joker 15%", "-0,30")]),
        response(payments=[payment("BON", "1,99")]),
        response(payments=[payment(CARD, "1,99"), payment("OSTATAK NOVCA", "0,01")]),
        response(receipt_number="100-2000-300"),
        response(store_name=" "),
        response(lines=[]),
        '{"store_name": "SYNTHETIC STORE"}',
        "not json",
        "",
    ],
)
def test_unreadable_response_is_invalid_and_writes_nothing(pdf: Path, answer: str) -> None:
    fake = FakePorts(answers=[pass1_response(), answer])
    result = run(pdf, fake)
    assert isinstance(result, Invalid)
    assert result.reason is FailureReason.NO_VALID_RESULT
    assert fake.written == []


def test_lines_not_matching_settlements_are_invalid(pdf: Path) -> None:
    fake = FakePorts(
        answers=[
            pass1_response(),
            response(payments=[payment(CARD, "2,50")], total="2,50"),
        ]
    )
    result = run(pdf, fake)
    assert isinstance(result, Invalid)
    assert result.reason is FailureReason.ITEMS_SETTLEMENT_MISMATCH
    assert fake.written == []


def test_total_not_matching_payments_is_invalid(pdf: Path) -> None:
    fake = FakePorts(answers=[pass1_response(), response(total="2,99")])
    result = run(pdf, fake)
    assert isinstance(result, Invalid)
    assert result.reason is FailureReason.TOTAL_SETTLEMENT_MISMATCH
    assert fake.written == []


def test_a_cent_of_rounding_is_tolerated(pdf: Path) -> None:
    fake = FakePorts(
        answers=[
            pass1_response(),
            response(total="2,00", payments=[payment(CARD, "2,00")]),
        ]
    )
    assert isinstance(run(pdf, fake), Stored)


def test_gemini_error_propagates_and_writes_nothing(pdf: Path) -> None:
    fake = FakePorts(error=RuntimeError("upstream failed"))
    with pytest.raises(RuntimeError, match="upstream failed"):
        run(pdf, fake)
    assert fake.written == []
