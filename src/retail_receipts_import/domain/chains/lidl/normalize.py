"""Turns a Lidl pass-2 response into a `NormalizedReceipt`, applying Lidl's printing rules."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.lidl.schema import LidlLine, LidlPass2, LidlPayment
from retail_receipts_import.domain.chains.printed import (
    DATE,
    fold,
    money,
    quantity,
    stripped,
)
from retail_receipts_import.domain.receipt import (
    NormalizedReceipt,
    ReceiptLine,
    Settlement,
    SettlementKind,
    zagreb_to_utc,
)

# Accepts HH:MM or HH:MM:SS from the "Datum:" line; seconds are dropped by zagreb_to_utc.
TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")


def normalize(response: str, chain_id: str) -> NormalizedReceipt:
    try:
        raw = LidlPass2.model_validate_json(response)
    except ValidationError as exc:
        # The error count only: the errors themselves would echo receipt content into logs.
        raise UnreadableReceipt(f"response fails the schema ({exc.error_count()} errors)") from None
    lines, deposit_refunds = _lines(raw.lines)
    settlements = _settlements(raw.payments, deposit_refunds)
    try:
        return NormalizedReceipt(
            payload_version=1,
            chain_id=chain_id,
            store_name=None,
            branch_number=_branch(raw.pj, raw.ibr),
            receipt_number=stripped(raw.receipt_number),
            store_address=stripped(raw.store_address),
            purchased_at=zagreb_to_utc(_purchase_time(raw.purchase_date, raw.purchase_time)),
            # The total is the value of the goods, and za platiti has the deposit refunds taken
            # off, wherever the model listed them.
            total=money(raw.total, "total") + _refunded(settlements),
            lines=lines,
            settlements=settlements,
        )
    except ValidationError as exc:
        raise UnreadableReceipt(f"receipt fails the model ({exc.error_count()} errors)") from None


def normalize_pass1_time(purchase_date: str, purchase_time: str) -> datetime | None:
    try:
        if not purchase_date or not purchase_time:
            return None
        date = DATE.fullmatch(purchase_date.strip())
        time = TIME.fullmatch(purchase_time.strip())
        if date is None or time is None:
            return None
        day, month, year = (int(part) for part in date.groups())
        hour, minute = int(time.group(1)), int(time.group(2))
        return zagreb_to_utc(datetime(year, month, day, hour, minute))
    except Exception:
        return None


def _branch(pj: str | None, ibr: str | None) -> str:
    cleaned_pj = stripped(pj)
    if cleaned_pj is not None:
        val = cleaned_pj.removeprefix("PJ:").removeprefix("PJ").strip()
        if val.isdigit():
            return val
    cleaned_ibr = stripped(ibr)
    if cleaned_ibr is not None:
        val = cleaned_ibr.removeprefix("IBR:").removeprefix("IBR").strip()
        first_segment = val.split("/")[0].strip()
        if first_segment.isdigit():
            return first_segment
    raise UnreadableReceipt(f"neither PJ {pj!r} nor IBR {ibr!r} gives a numeric branch")


def _purchase_time(date_text: str, time_text: str) -> datetime:
    date = DATE.fullmatch(date_text.strip())
    time = TIME.fullmatch(time_text.strip())
    if date is None or time is None:
        raise UnreadableReceipt(f"purchase time {date_text!r} {time_text!r} cannot be read")
    day, month, year = (int(part) for part in date.groups())
    hour, minute = int(time.group(1)), int(time.group(2))
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        raise UnreadableReceipt(f"purchase time {date_text!r} {time_text!r} is no date") from None


def _is_info(text: str) -> bool:
    label = fold(text)
    return (
        "POVRATNA NAKNADA" in label
        or "POV. NAKNADA" in label
        or "POV.NAKNADA" in label
        or "USTEDA" in label
        or label.strip() == "POPUST"
    )


@dataclass
class _Item:
    row: LidlLine
    text: str
    quantity: Decimal
    amount: Decimal
    discount: Decimal = Decimal(0)
    discount_text: str | None = None


def _lines(rows: list[LidlLine]) -> tuple[list[ReceiptLine], list[Settlement]]:
    items: list[_Item] = []
    deposit_refunds: list[Settlement] = []

    for row in rows:
        if _is_info(row.text):
            continue
        label = fold(row.text)
        if "PROMJENA CIJENE" in label:
            change_amount = money(row.amount, "price change")
            if change_amount != Decimal(0):
                raise UnreadableReceipt(f"non-zero price change {row.amount!r}")
            continue
        if "OTKUP AMBALA" in label:
            refund_amount = money(row.amount, "deposit refund")
            deposit_refunds.append(
                Settlement(
                    kind=SettlementKind.DEPOSIT_REFUND,
                    printed_text=row.text.strip(),
                    amount=abs(refund_amount),
                )
            )
            continue

        amount = money(row.amount, "line amount")
        if row.quantity is not None:
            qty = quantity(row.quantity)
            text = row.text.strip()
            if qty == Decimal(1) and re.match(r"^1\s+", text):
                text = re.sub(r"^1\s+", "", text).strip()
            items.append(_Item(row=row, text=text, quantity=qty, amount=amount))
            continue

        if amount >= Decimal(0) or not items:
            raise UnreadableReceipt(f"row {row.text!r} is neither an item nor a discount")
        item = items[-1]
        item.discount -= amount
        text = row.text.strip()
        item.discount_text = f"{item.discount_text}; {text}" if item.discount_text else text

    return [_line(item) for item in items], deposit_refunds


def _line(item: _Item) -> ReceiptLine:
    unit = item.row.unit
    price = item.row.unit_price
    return ReceiptLine(
        printed_text=item.text,
        quantity=item.quantity,
        unit="kg" if unit and unit.strip().lower().startswith("kg") else None,
        unit_price=None if price is None else money(price, "unit price"),
        printed_amount=item.amount,
        separate_discount=item.discount,
        discount_text=item.discount_text,
    )


def _settlements(
    payments: list[LidlPayment], deposit_refunds: list[Settlement]
) -> list[Settlement]:
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
            change = abs(amount)
            continue
        if "OTKUP AMBALA" in label:
            rows.append((SettlementKind.DEPOSIT_REFUND, payment.text.strip(), abs(amount)))
            continue
        if "NOVCANIC" in label or "GOTOVIN" in label:
            kind = SettlementKind.CASH
        elif "KARTIC" in label:
            kind = SettlementKind.CARD
        else:
            raise UnreadableReceipt(f"payment row {payment.text!r} is not a known kind")
        rows.append((kind, payment.text.strip(), amount))

    if change is not None:
        cash = [i for i, (kind, _, _) in enumerate(rows) if kind is SettlementKind.CASH]
        if len(cash) != 1:
            raise UnreadableReceipt("change is printed without exactly one cash row")
        kind, text, cash_amount = rows[cash[0]]
        rows[cash[0]] = (kind, text, cash_amount - change)

    settlements = [
        Settlement(kind=kind, printed_text=text, amount=amount) for kind, text, amount in rows
    ]
    settlements.extend(deposit_refunds)
    return settlements


def _refunded(settlements: list[Settlement]) -> Decimal:
    return sum(
        (s.amount for s in settlements if s.kind is SettlementKind.DEPOSIT_REFUND), Decimal(0)
    )
