"""Turns a Müller pass-2 response into a `NormalizedReceipt` by Müller's printing rules."""

import re
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.mueller.schema import (
    MuellerLine,
    MuellerPass2,
    MuellerPayment,
)
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
from retail_receipts_import.domain.receipt import (
    LineKind,
    NormalizedReceipt,
    ReceiptLine,
    Settlement,
    SettlementKind,
    zagreb_to_utc,
)

# The footer prints HH:MM and the card slip HH:MM:SS, minutes apart on some receipts; refusing
# seconds turns a slip copied by mistake into a misread instead of a dedup key a minute off.
TIME = re.compile(r"(\d{2}):(\d{2})")


def normalize(response: str, chain_id: str) -> NormalizedReceipt:
    raw = parse_pass2(MuellerPass2, response)
    try:
        lines = _lines(raw.lines)
        settlements = _settlements(raw.payments)
        receipt_number, branch = _receipt_number_and_branch(raw.receipt_number)
        amount_to_pay = money(raw.amount_to_pay, "amount to pay")
        if amount_to_pay < Decimal(0):
            raise UnreadableReceipt(f"amount to pay {raw.amount_to_pay!r} is negative")
        total = _total(amount_to_pay, settlements)
        return NormalizedReceipt(
            payload_version=1,
            chain_id=chain_id,
            store_name=_store_name(raw.store_name),
            branch_number=branch,
            receipt_number=receipt_number,
            store_address=_store_address(raw.store_address),
            loyalty_card_number=None,
            purchased_at=zagreb_to_utc(
                purchase_time(DATE, TIME, raw.purchase_date, raw.purchase_time)
            ),
            total=total,
            lines=lines,
            settlements=settlements,
        )
    except ValidationError as exc:
        raise UnreadableReceipt(f"receipt fails the model ({exc.error_count()} errors)") from None


def normalize_pass1_time(purchase_date: str, purchase_time: str) -> datetime | None:
    return pass1_time(DATE, TIME, purchase_date, purchase_time)


def _total(amount_to_pay: Decimal, settlements: list[Settlement]) -> Decimal:
    bonus = sum(
        (s.amount for s in settlements if s.kind is SettlementKind.BONUS_POINTS),
        Decimal(0),
    )
    return amount_to_pay + bonus


def _receipt_number_and_branch(receipt_number: str | None) -> tuple[str, str]:
    val = stripped(receipt_number)
    if val is None:
        raise UnreadableReceipt("missing receipt number")
    cleaned = re.sub(r"^RB\s*:\s*", "", val, flags=re.IGNORECASE).strip()
    if not cleaned:
        raise UnreadableReceipt(f"receipt number {receipt_number!r} has no number value")
    segments = cleaned.split("/")
    if len(segments) < 3:
        raise UnreadableReceipt(f"receipt number {receipt_number!r} has fewer than three segments")
    branch = segments[1].strip()
    if not branch:
        raise UnreadableReceipt(f"receipt number {receipt_number!r} has empty branch segment")
    return cleaned, branch


def _store_name(store_name: str | None) -> str | None:
    name = stripped(store_name)
    if name is None:
        return None
    folded = fold(name)
    if "ORESKOVIC" in folded or "TRGOVINA" in folded:
        return None
    cleaned = " ".join(name.split())
    return cleaned or None


def _store_address(store_address: str | None) -> str | None:
    addr = stripped(store_address)
    if addr is None:
        return None
    lines = [line.strip() for line in addr.splitlines() if line.strip()]
    filtered = [line for line in lines if "oreskovic" not in fold(line).lower()]
    if not filtered:
        return None
    combined = ", ".join(filtered)
    cleaned = re.sub(r"(?:,\s*)?Tel(?:efon|\.|\:).*$", "", combined, flags=re.IGNORECASE).strip()
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _is_info(text: str) -> bool:
    label = fold(text)
    return (
        "MEĐUZBROJ" in label or "MEDUZBROJ" in label or "PDV" in label or "PONOVNI ISPIS" in label
    )


def _lines(rows: list[MuellerLine]) -> list[ReceiptLine]:
    result: list[ReceiptLine] = []

    for row in rows:
        raw_text = stripped(row.text)
        if raw_text is None or _is_info(raw_text):
            continue

        # Drop one trailing standalone ' *' (loyalty-exclusion marker) and collapse whitespace runs.
        cleaned_text = re.sub(r"\s+\*$", "", raw_text)
        cleaned_text = " ".join(cleaned_text.split())
        if not cleaned_text:
            continue

        # Müller glues a single VAT letter to the amount (e.g. '11,99a', '0,10b').
        val = row.amount.strip()
        if val and val[-1].isalpha():
            val = val[:-1].strip()
        amount = money(val, "line amount")
        if amount <= Decimal(0):
            raise UnreadableReceipt(f"item {row.text!r} amount is not positive")

        is_deposit = fold(cleaned_text) == "POVRATNA NAKNADA"

        if row.quantity is None or stripped(row.quantity) is None:
            if not is_deposit:
                raise UnreadableReceipt(f"item row {row.text!r} lacks quantity")
            qty = Decimal(1)
        else:
            qty = quantity(row.quantity)
            if qty <= Decimal(0):
                raise UnreadableReceipt(f"item row {row.text!r} quantity is not positive")

        if row.unit_price is None or stripped(row.unit_price) is None:
            raise UnreadableReceipt(f"item row {row.text!r} lacks unit price")
        price = money(row.unit_price, "unit price")
        if price <= Decimal(0):
            raise UnreadableReceipt(f"item row {row.text!r} unit price is not positive")

        if row.discount is not None and stripped(row.discount) is not None:
            disc_amount = money(row.discount, "discount")
            if disc_amount >= Decimal(0):
                raise UnreadableReceipt(f"discount {row.discount!r} is not negative")
            popust = disc_amount
            included_discount = abs(disc_amount)
        else:
            popust = Decimal(0)
            included_discount = Decimal(0)

        # The printed columns check each other, so a misread digit in any of them is caught here
        # rather than surfacing later as a receipt that does not balance.
        if qty * price + popust != amount:
            raise UnreadableReceipt(
                f"row {row.text!r} fails Kom x Cijena + Popust = Iznos: "
                f"{qty} * {price} + {popust} != {amount}"
            )

        discount_note = stripped(row.discount_note)
        discount_text = " ".join(discount_note.split()) if discount_note else None

        result.append(
            ReceiptLine(
                kind=LineKind.SALE,
                printed_text=cleaned_text,
                quantity=qty,
                unit=None,
                unit_price=price,
                printed_amount=amount,
                included_discount=included_discount,
                discount_text=discount_text,
            )
        )

    if not result:
        raise UnreadableReceipt("receipt contains no items")

    return result


def _settlements(payments: list[MuellerPayment]) -> list[Settlement]:
    rows: list[tuple[SettlementKind, str, Decimal]] = []
    change: Decimal | None = None

    for payment in payments:
        text = stripped(payment.text)
        if text is None or _is_info(text):
            continue
        label = fold(text)
        amount = money(payment.amount, "payment")
        if "POVRAT NOVCA" in label:
            if change is not None:
                raise UnreadableReceipt("two change rows")
            change = abs(amount)
            continue
        if "GOTOVINA" in label:
            kind = SettlementKind.CASH
        elif "KARTIC" in label:
            kind = SettlementKind.CARD
        elif "BODOVI" in label:
            kind = SettlementKind.BONUS_POINTS
        else:
            raise UnreadableReceipt(f"payment row {payment.text!r} is not a known kind")

        if amount <= Decimal(0):
            raise UnreadableReceipt(f"payment row {payment.text!r} amount is not positive")

        rows.append((kind, " ".join(text.split()), amount))

    if change:
        cash = [i for i, (kind, _, _) in enumerate(rows) if kind is SettlementKind.CASH]
        if len(cash) != 1:
            raise UnreadableReceipt("change without exactly one cash row")
        idx = cash[0]
        kind, text, cash_amount = rows[idx]
        netted_cash = cash_amount - change
        if netted_cash <= Decimal(0):
            raise UnreadableReceipt("change equals or exceeds cash payment")
        rows[idx] = (kind, text, netted_cash)

    settlements = [
        Settlement(kind=kind, printed_text=text, amount=amount) for kind, text, amount in rows
    ]
    if not settlements:
        raise UnreadableReceipt("receipt contains no payments")
    return settlements
