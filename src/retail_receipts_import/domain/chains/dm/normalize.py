"""Turns a DM pass-2 response into a `NormalizedReceipt` by DM's printing rules."""

import re
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from retail_receipts_import.domain.chains.dm.schema import (
    DmLine,
    DmPass2,
    DmPayment,
)
from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.printed import (
    SHORT_YEAR_DATE,
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

# Accepts HH:MM or HH:MM:SS from the header line; seconds are dropped by zagreb_to_utc.
TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")


def normalize(response: str, chain_id: str) -> NormalizedReceipt:
    """Parses raw pass-2 DM JSON response and builds NormalizedReceipt."""
    raw = parse_pass2(DmPass2, response)
    try:
        lines = _lines(raw.lines)
        settlements = _settlements(raw.payments)
        receipt_number, branch = _receipt_number_and_branch(raw.receipt_number)
        return NormalizedReceipt(
            payload_version=1,
            chain_id=chain_id,
            store_name=None,
            branch_number=branch,
            receipt_number=receipt_number,
            store_address=_store_address(raw.store_address),
            loyalty_card_number=None,
            purchased_at=zagreb_to_utc(
                purchase_time(SHORT_YEAR_DATE, TIME, raw.purchase_date, raw.purchase_time)
            ),
            total=money(raw.total, "total"),
            lines=lines,
            settlements=settlements,
        )
    except ValidationError as exc:
        raise UnreadableReceipt(f"receipt fails the model ({exc.error_count()} errors)") from None


def normalize_pass1_time(purchase_date: str, purchase_time: str) -> datetime | None:
    """Converts DM pass-1 purchase date and time strings into a UTC datetime."""
    return pass1_time(SHORT_YEAR_DATE, TIME, purchase_date, purchase_time)


def _receipt_number_and_branch(receipt_number: str | None) -> tuple[str, str]:
    val = stripped(receipt_number)
    if val is None:
        raise UnreadableReceipt("missing receipt number")
    cleaned = re.sub(
        r"^(?:Broj|Br\.?)\s*(?:računa|racuna)\s*:\s*", "", val, flags=re.IGNORECASE
    ).strip()
    if not cleaned:
        raise UnreadableReceipt(f"receipt number {receipt_number!r} has no number value")
    segments = cleaned.split("/")
    if len(segments) < 3:
        raise UnreadableReceipt(f"receipt number {receipt_number!r} has fewer than three segments")
    branch = segments[1].strip()
    if not branch:
        raise UnreadableReceipt(f"receipt number {receipt_number!r} has empty branch segment")
    return cleaned, branch


def _store_address(store_address: str | None) -> str | None:
    addr = stripped(store_address)
    if addr is None:
        return None
    # The header image prints street and city on two lines, the text layer on one; join them so
    # one shop always gives one address. The head office line is the company's, not the shop's.
    parts = [p.strip() for p in addr.splitlines() if p.strip() and "kovinska" not in p.lower()]
    return ", ".join(parts) or None


def _is_info(text: str) -> bool:
    label = fold(text)
    return "PDV" in label or "OSNOVICA" in label or "ACTIVE BEAUTY" in label


def _parse_quantity(raw_qty: str, is_storno: bool = False) -> Decimal:
    val = raw_qty.strip()
    if is_storno:
        val = val.lstrip("-").strip()
    val = re.sub(r"\s*kom\b", "", val, flags=re.IGNORECASE).strip()
    qty = quantity(val)
    return -qty if is_storno else qty


def _lines(rows: list[DmLine]) -> list[ReceiptLine]:
    result: list[ReceiptLine] = []
    storno_marker = False
    cancelled_indices: set[int] = set()

    for row in rows:
        text = stripped(row.text)
        if text is None:
            continue

        folded = fold(text).strip()
        if folded == "STORNO RETKA":
            storno_marker = True
            continue

        if _is_info(text):
            continue

        amount = money(row.amount, "line amount")

        if storno_marker:
            if amount >= Decimal(0):
                raise UnreadableReceipt(f"storno row {row.text!r} amount is not negative")
            if row.quantity is None:
                raise UnreadableReceipt(f"storno row {row.text!r} lacks quantity")

            qty = _parse_quantity(row.quantity, is_storno=True)
            price = (
                money(row.unit_price, "unit price")
                if row.unit_price is not None and stripped(row.unit_price) is not None
                else None
            )

            cancels: int | None = None
            abs_price = abs(price) if price is not None else None
            for idx in reversed(range(len(result))):
                pos = idx + 1
                cand = result[idx]
                if cand.kind is not LineKind.SALE:
                    continue
                if pos in cancelled_indices:
                    continue
                cand_abs_price = abs(cand.unit_price) if cand.unit_price is not None else None
                if fold(cand.printed_text).strip() == folded and cand_abs_price == abs_price:
                    cancels = pos
                    break

            if cancels is None:
                raise UnreadableReceipt(
                    f"storno row {row.text!r} has no matching earlier sale line"
                )

            cancelled_indices.add(cancels)
            result.append(
                ReceiptLine(
                    kind=LineKind.STORNO,
                    cancels_line=cancels,
                    printed_text=text,
                    quantity=qty,
                    unit=None,
                    unit_price=price,
                    printed_amount=amount,
                )
            )
            storno_marker = False
            continue

        if amount < Decimal(0) or (row.quantity and row.quantity.strip().startswith("-")):
            raise UnreadableReceipt(f"negative row {row.text!r} not after STORNO RETKA")

        if row.quantity is None:
            raise UnreadableReceipt(f"item row {row.text!r} lacks quantity")

        qty = _parse_quantity(row.quantity, is_storno=False)
        price = (
            money(row.unit_price, "unit price")
            if row.unit_price is not None and stripped(row.unit_price) is not None
            else None
        )
        result.append(
            ReceiptLine(
                kind=LineKind.SALE,
                printed_text=text,
                quantity=qty,
                unit=None,
                unit_price=price,
                printed_amount=amount,
            )
        )

    if storno_marker:
        raise UnreadableReceipt("STORNO RETKA marker without following item row")

    if not result:
        raise UnreadableReceipt("receipt contains no items")

    return result


def _settlements(payments: list[DmPayment]) -> list[Settlement]:
    rows: list[tuple[SettlementKind, str, Decimal]] = []
    change: Decimal | None = None

    for payment in payments:
        text = stripped(payment.text)
        if text is None or _is_info(text):
            continue
        label = fold(text)
        amount = money(payment.amount, "payment")
        if "POVRAT NOVACA" in label:
            if change is not None:
                raise UnreadableReceipt("two change rows")
            change = abs(amount)
            continue
        if "GOTOVINA" in label:
            kind = SettlementKind.CASH
        elif any(card in label for card in ("MASTERCARD", "MAESTRO", "VISA", "DINERS", "KARTICA")):
            kind = SettlementKind.CARD
        else:
            raise UnreadableReceipt(f"payment row {payment.text!r} is not a known kind")
        rows.append((kind, text, abs(amount)))

    if change:
        cash = [i for i, (kind, _, _) in enumerate(rows) if kind is SettlementKind.CASH]
        if len(cash) != 1:
            raise UnreadableReceipt("change without exactly one cash row")
        idx = cash[0]
        kind, text, cash_amount = rows[idx]
        rows[idx] = (kind, text, cash_amount - change)

    settlements = [
        Settlement(kind=kind, printed_text=text, amount=amount) for kind, text, amount in rows
    ]
    if not settlements:
        raise UnreadableReceipt("receipt contains no payments")
    return settlements
