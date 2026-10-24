"""Turns a Kaufland pass-2 response into a `NormalizedReceipt` by Kaufland's printing rules."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.kaufland.schema import (
    KauflandLine,
    KauflandPass2,
    KauflandPayment,
)
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
    NormalizedReceipt,
    ReceiptLine,
    Settlement,
    SettlementKind,
    zagreb_to_utc,
)

# Accepts HH:MM or HH:MM:SS from the fiscal line; seconds are dropped by zagreb_to_utc.
TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")


def normalize(response: str, chain_id: str) -> NormalizedReceipt:
    """Parses raw pass-2 Kaufland JSON response and builds NormalizedReceipt."""
    raw = parse_pass2(KauflandPass2, response)
    # Lines and settlements are models too, so their validation errors must be caught here as well.
    try:
        lines, deposit_refunds = _lines(raw.lines)
        settlements = _settlements(raw.payments, deposit_refunds)
        branch, store_name = _branch_and_store_name(raw.pj_line, raw.receipt_number)
        return NormalizedReceipt(
            payload_version=1,
            chain_id=chain_id,
            store_name=store_name,
            branch_number=branch,
            receipt_number=_receipt_number(raw.receipt_number),
            store_address=stripped(raw.store_address),
            loyalty_card_number=_loyalty_card(raw.loyalty_card),
            purchased_at=zagreb_to_utc(
                purchase_time(SHORT_YEAR_DATE, TIME, raw.purchase_date, raw.purchase_time)
            ),
            # The total is the value of the goods, and Za platiti has the deposit refunds taken off.
            total=money(raw.total, "total") + sum((r.amount for r in deposit_refunds), Decimal(0)),
            lines=lines,
            settlements=settlements,
        )
    except ValidationError as exc:
        raise UnreadableReceipt(f"receipt fails the model ({exc.error_count()} errors)") from None


def normalize_pass1_time(purchase_date: str, purchase_time: str) -> datetime | None:
    """Converts Kaufland pass-1 purchase date and time strings into a UTC datetime."""
    return pass1_time(SHORT_YEAR_DATE, TIME, purchase_date, purchase_time)


def _branch_and_store_name(
    pj_line: str | None, receipt_number: str | None
) -> tuple[str, str | None]:
    cleaned_pj = stripped(pj_line)
    if cleaned_pj is None:
        raise UnreadableReceipt("missing PJ line")
    match = re.search(r"PJ\s*(\d+)", cleaned_pj, flags=re.IGNORECASE)
    if not match:
        raise UnreadableReceipt(f"PJ line {pj_line!r} lacks branch digits")
    branch = match.group(1)

    cleaned_rcpt = stripped(receipt_number)
    if cleaned_rcpt is None:
        raise UnreadableReceipt("missing receipt number")
    val = re.sub(r"^(?:Račun|Racun)\s*", "", cleaned_rcpt, flags=re.IGNORECASE).strip()
    segments = val.split("/")
    if len(segments) < 2:
        raise UnreadableReceipt(f"receipt number {receipt_number!r} does not have branch segment")
    rcpt_branch = segments[1].strip()
    if rcpt_branch != branch:
        raise UnreadableReceipt(
            f"branch {branch!r} disagrees with receipt number {receipt_number!r}"
        )

    comma_idx = cleaned_pj.find(",")
    if comma_idx != -1:
        store_name = cleaned_pj[comma_idx + 1 :].strip() or None
    else:
        store_name = cleaned_pj[match.end() :].strip().lstrip(",").strip() or None
    return branch, store_name


def _receipt_number(receipt_number: str | None) -> str | None:
    val = stripped(receipt_number)
    if val is None:
        return None
    cleaned = re.sub(r"^(?:Račun|Racun)\s*", "", val, flags=re.IGNORECASE).strip()
    return cleaned or None


def _loyalty_card(loyalty_card: str | None) -> str | None:
    val = stripped(loyalty_card)
    if val is None:
        return None
    cleaned = re.sub(r"^Kaufland\s+Card\s*:\s*", "", val, flags=re.IGNORECASE).strip()
    return cleaned or None


def _is_info(text: str) -> bool:
    label = fold(text)
    return (
        # Đ has no NFKD decomposition, so fold keeps it; the model may also spell it D or DJ.
        re.search(r"ME(?:Đ|DJ|D)USUMA", label) is not None
        or label.strip() == "SUMA"
        or label.startswith("SUMA ")
        or label.startswith("SUMA:")
        or "POVRATNA NAKNADA" in label
        or "POV. NAKNADA" in label
        or "POV.NAKNADA" in label
        or "HRK" in label
        or "PDV" in label
        or "BEZ PRAVA NA POPUST" in label
        or bool(re.search(r"KAUFLAND\s+CARD\s*:", label))
    )


@dataclass
class _Item:
    """Intermediate item accumulator used during Kaufland line normalization."""

    row: KauflandLine
    text: str
    quantity: Decimal
    amount: Decimal
    included_discount: Decimal = Decimal(0)
    discount: Decimal = Decimal(0)
    discount_text: str | None = None


def _lines(rows: list[KauflandLine]) -> tuple[list[ReceiptLine], list[Settlement]]:
    items: list[_Item] = []
    deposit_refunds: list[Settlement] = []

    for row in rows:
        if _is_info(row.text):
            continue
        folded = fold(row.text).strip()
        if folded.startswith("AMB.") or folded.startswith("AMBALAZ"):
            refund_amount = money(row.amount, "deposit refund")
            deposit_refunds.append(
                Settlement(
                    kind=SettlementKind.DEPOSIT_REFUND,
                    printed_text=row.text.strip(),
                    amount=abs(refund_amount),
                )
            )
            continue
        if "STEDITE" in folded:
            if not items:
                raise UnreadableReceipt("Štedite row without preceding item")
            saved = abs(money(row.amount, "included discount"))
            items[-1].included_discount += saved
            continue

        amount = money(row.amount, "line amount")
        if folded.startswith("BOCA ZA PIVO") and amount < Decimal(0):
            deposit_refunds.append(
                Settlement(
                    kind=SettlementKind.DEPOSIT_REFUND,
                    printed_text=row.text.strip(),
                    amount=abs(amount),
                )
            )
            continue

        if row.quantity is not None:
            if amount < Decimal(0):
                raise UnreadableReceipt(f"negative row {row.text!r} is not a known deposit refund")
            qty = quantity(row.quantity)
            items.append(_Item(row=row, text=row.text.strip(), quantity=qty, amount=amount))
            continue

        if amount >= Decimal(0) or not items:
            raise UnreadableReceipt(f"row {row.text!r} is neither an item nor a discount")
        item = items[-1]
        item.discount += abs(amount)
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
        included_discount=item.included_discount,
        separate_discount=item.discount,
        discount_text=item.discount_text,
    )


def _settlements(
    payments: list[KauflandPayment], deposit_refunds: list[Settlement]
) -> list[Settlement]:
    rows: list[tuple[SettlementKind, str, Decimal]] = []
    change: Decimal | None = None

    for payment in payments:
        if _is_info(payment.text):
            continue
        label = fold(payment.text)
        amount = money(payment.amount, "payment")
        if "VRATITI" in label:
            if change is not None:
                raise UnreadableReceipt("two change rows")
            change = abs(amount)
            continue
        if "EURO" in label:
            kind = SettlementKind.CASH
        elif "KARTIC" in label:
            kind = SettlementKind.CARD
        else:
            raise UnreadableReceipt(f"payment row {payment.text!r} is not a known kind")
        rows.append((kind, payment.text.strip(), amount))

    if change is not None and change > Decimal(0):
        cash = [i for i, (kind, _, _) in enumerate(rows) if kind is SettlementKind.CASH]
        if len(cash) != 1:
            raise UnreadableReceipt("change > 0 without exactly one cash row")
        idx = cash[0]
        kind, text, cash_amount = rows[idx]
        rows[idx] = (kind, text, cash_amount - change)

    settlements = [
        Settlement(kind=kind, printed_text=text, amount=amount) for kind, text, amount in rows
    ]
    settlements.extend(deposit_refunds)
    return settlements
