"""Turns a Spar pass-2 response into a `NormalizedReceipt`, applying Spar's printing rules."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.printed import (
    DATE,
    fold,
    money,
    parse_pass2,
    pass1_time,
    purchase_time,
    quantity,
    stripped,
)
from retail_receipts_import.domain.chains.spar.schema import SparLine, SparPass2, SparPayment
from retail_receipts_import.domain.receipt import (
    NormalizedReceipt,
    ReceiptLine,
    Settlement,
    SettlementKind,
    zagreb_to_utc,
)

# Strict on purpose: a value in any other shape is a misread, and guessing would store it.
TIME = re.compile(r"(\d{1,2}):(\d{2})")


def normalize(response: str, chain_id: str) -> NormalizedReceipt:
    raw = parse_pass2(SparPass2, response)
    try:
        return NormalizedReceipt(
            payload_version=1,
            chain_id=chain_id,
            store_name=raw.store_name.strip(),
            branch_number=_branch(raw.receipt_number),
            receipt_number=stripped(raw.receipt_number),
            store_address=stripped(raw.store_address),
            purchased_at=zagreb_to_utc(
                purchase_time(DATE, TIME, raw.purchase_date, raw.purchase_time)
            ),
            total=money(raw.total, "total"),
            lines=_lines(raw.lines),
            settlements=_settlements(raw.payments),
        )
    except ValidationError as exc:
        raise UnreadableReceipt(f"receipt fails the model ({exc.error_count()} errors)") from None


def normalize_pass1_time(purchase_date: str, purchase_time: str) -> datetime | None:
    return pass1_time(DATE, TIME, purchase_date, purchase_time)


def _branch(receipt_number: str | None) -> str | None:
    # Spar prints `sequence/branch/till`; the branch is the middle segment.
    number = stripped(receipt_number)
    if number is None:
        return None
    parts = number.split("/")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise UnreadableReceipt(f"receipt number {number!r} is not three numeric segments")
    return parts[1]


@dataclass
class _Item:
    row: SparLine
    quantity: Decimal
    amount: Decimal
    discount: Decimal = Decimal(0)
    discount_text: str | None = None


def _lines(rows: list[SparLine]) -> list[ReceiptLine]:
    """Items in print order, each carrying the discount rows printed under it.

    Spar prints a discount such as `Joker 15% -0,30` as its own row under the item it reduces,
    so the item keeps its printed amount and the discount comes off on top of it.
    """
    items: list[_Item] = []
    for row in rows:
        if _is_info(row.text):
            continue
        amount = money(row.amount, "line amount")
        if row.quantity is not None:
            items.append(_Item(row=row, quantity=quantity(row.quantity), amount=amount))
            continue
        if amount >= 0 or not items:
            raise UnreadableReceipt(f"row {row.text!r} is neither an item nor a discount")
        item = items[-1]
        item.discount -= amount
        text = row.text.strip()
        item.discount_text = f"{item.discount_text}; {text}" if item.discount_text else text
    return [_line(item) for item in items]


def _line(item: _Item) -> ReceiptLine:
    unit = item.row.unit
    price = item.row.unit_price
    # Only the printed amount is taken: a weighed line's kg times price is rounded on print.
    return ReceiptLine(
        printed_text=item.row.text.strip(),
        quantity=item.quantity,
        unit="kg" if unit and unit.strip().lower().startswith("kg") else None,
        unit_price=None if price is None else money(price, "unit price"),
        printed_amount=item.amount,
        separate_discount=item.discount,
        discount_text=item.discount_text,
    )


def _is_info(text: str) -> bool:
    """Rows printed for information only, dropped if the model lists them anyway.

    `Povratna naknada` sums deposits that are already inside the line amounts, and
    `Vaša ušteda` sums discounts already printed as their own rows; counting either would
    count it twice.
    """
    label = fold(text)
    return "POVRATNA NAKNADA" in label or "USTEDA" in label


def _settlements(payments: list[SparPayment]) -> list[Settlement]:
    """Card and cash rows in print order, with the printed change taken off the cash row."""
    rows: list[tuple[SettlementKind, str, Decimal]] = []
    change: Decimal | None = None
    for payment in payments:
        if _is_info(payment.text):
            continue
        label = fold(payment.text)
        amount = money(payment.amount, "payment")
        if "OSTATAK" in label:
            if change is not None:
                raise UnreadableReceipt("two change rows")
            change = amount
            continue
        # Cash is matched first: its row starts with PLACANJE like a card row.
        if "GOTOVIN" in label:
            kind = SettlementKind.CASH
        elif label.startswith("PLA"):
            kind = SettlementKind.CARD
        else:
            raise UnreadableReceipt(f"payment row {payment.text!r} is not a known kind")
        rows.append((kind, payment.text.strip(), amount))

    if change is not None:
        cash = [i for i, (kind, _, _) in enumerate(rows) if kind is SettlementKind.CASH]
        if len(cash) != 1:
            raise UnreadableReceipt("change is printed without exactly one cash row")
        kind, text, amount = rows[cash[0]]
        rows[cash[0]] = (kind, text, amount - change)
    return [Settlement(kind=kind, printed_text=text, amount=amount) for kind, text, amount in rows]
