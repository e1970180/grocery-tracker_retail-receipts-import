"""The receipt shape every chain plug-in produces, and the checks that gate storing it.

Everything here is pure: no database, no clock, no network. Money is Decimal throughout, because
floats would drift from the numeric(12,2) columns the amounts are written to.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from retail_receipts_import.domain.chains import RESERVED_IDS, is_chain_id

PAYLOAD_VERSION = 1

# Shops print in Zagreb local time; the stored purchase time is UTC.
STORE_TIMEZONE = ZoneInfo("Europe/Zagreb")

# A printed receipt can be off by a cent after rounding; anything larger is a misread.
TOLERANCE = Decimal("0.01")

Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
Quantity = Annotated[Decimal, Field(max_digits=12, decimal_places=3)]


class SettlementKind(StrEnum):
    CARD = "card"
    CASH = "cash"
    BONUS_POINTS = "bonus_points"
    COUPON = "coupon"
    DEPOSIT_REFUND = "deposit_refund"


class LineKind(StrEnum):
    SALE = "sale"
    STORNO = "storno"
    RETURN = "return"


class SourceKind(StrEnum):
    TELEGRAM = "telegram"


class ItemsSettlementMismatch(Exception):
    """The printed lines do not add up to the printed payments, beyond the tolerance."""

    def __init__(self, difference: Decimal) -> None:
        self.difference = difference
        super().__init__(f"lines differ from settlements by {difference}")


class TotalSettlementMismatch(Exception):
    """The printed total is not the card plus cash paid, beyond the tolerance."""

    def __init__(self, difference: Decimal) -> None:
        self.difference = difference
        super().__init__(f"total differs from card plus cash by {difference}")


class ReceiptLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: LineKind = LineKind.SALE
    # 1-based position of the earlier sale line this storno cancels; the receipt checks it.
    cancels_line: int | None = None
    printed_text: str = Field(min_length=1)
    quantity: Quantity
    unit: str | None = None
    unit_price: Money | None = None
    printed_amount: Money
    included_discount: Money = Decimal(0)
    separate_discount: Money = Decimal(0)
    discount_text: str | None = None

    @model_validator(mode="after")
    def _signs_follow_kind(self) -> Self:
        # Storno and return lines are printed as negatives, so netting is plain addition.
        amounts = (self.printed_amount, self.included_discount, self.separate_discount)
        if self.kind is LineKind.SALE:
            if self.cancels_line is not None:
                raise ValueError("a sale line cannot cancel another line")
            if self.quantity <= 0:
                raise ValueError("a sale line needs a positive quantity")
            if any(value < 0 for value in amounts):
                raise ValueError("a sale line's amounts and discounts cannot be negative")
            return self
        if self.kind is LineKind.STORNO and self.cancels_line is None:
            raise ValueError("a storno line must name the line it cancels")
        if self.kind is LineKind.RETURN and self.cancels_line is not None:
            raise ValueError("a return line cancels no line")
        if self.quantity >= 0:
            raise ValueError(f"a {self.kind} line needs a negative quantity")
        if any(value > 0 for value in amounts):
            raise ValueError(f"a {self.kind} line's amounts and discounts cannot be positive")
        return self

    @property
    def regular_amount(self) -> Decimal:
        return self.printed_amount + self.included_discount

    @property
    def effective_amount(self) -> Decimal:
        return self.printed_amount - self.separate_discount


class Settlement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SettlementKind
    printed_text: str = Field(min_length=1)
    amount: Money

    @model_validator(mode="after")
    def _sign_follows_kind(self) -> Self:
        # Card and cash can be negative (a refund paid back to the card), the rest are payouts in.
        if self.kind not in (SettlementKind.CARD, SettlementKind.CASH) and self.amount <= 0:
            raise ValueError(f"a {self.kind} settlement must be positive")
        return self


def _utc_to_the_minute(value: datetime) -> datetime:
    # Checked by offset, not by tzinfo identity: a parsed "Z" carries its own UTC object.
    if value.utcoffset() != timedelta(0):
        raise ValueError("purchased_at must be UTC")
    if value.second or value.microsecond:
        raise ValueError("purchased_at must have zero seconds and microseconds")
    return value


PurchasedAt = Annotated[AwareDatetime, AfterValidator(_utc_to_the_minute)]


class NormalizedReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_version: Literal[1]
    chain_id: str
    store_name: str = Field(min_length=1)
    branch_number: str | None = None
    receipt_number: str | None = None
    store_address: str | None = None
    loyalty_card_number: str | None = None
    currency: Literal["EUR"] = "EUR"
    purchased_at: PurchasedAt
    total: Money
    lines: list[ReceiptLine] = Field(min_length=1)
    settlements: list[Settlement] = Field(min_length=1)

    @field_validator("chain_id")
    @classmethod
    def _chain_is_known_slug(cls, value: str) -> str:
        # The reserved ids are slugs too, so the slug check alone would let them through.
        if not is_chain_id(value) or value in RESERVED_IDS:
            raise ValueError("chain_id must be a reference slug, not a printed name or a sentinel")
        return value

    @model_validator(mode="after")
    def _netting_is_sound(self) -> Self:
        for position, line in enumerate(self.lines, start=1):
            if line.cancels_line is None:
                continue
            target = line.cancels_line
            if not 1 <= target <= len(self.lines):
                raise ValueError(f"line {position} cancels line {target}, which is out of range")
            if target >= position:
                raise ValueError(f"line {position} cancels line {target}, which is not earlier")
            if self.lines[target - 1].kind is not LineKind.SALE:
                raise ValueError(f"line {position} cancels line {target}, which is not a sale")
        # Running the netting here makes a bad receipt fail in the model, not inside the write.
        self.stored_lines()
        return self

    def stored_lines(self) -> list[ReceiptLine]:
        """The purchased lines with each storno netted into the sale line it cancels.

        Return lines and lines netted to zero quantity are dropped, so every stored line is a
        purchase that still stands.
        """
        netted: dict[int, ReceiptLine] = {
            position: line
            for position, line in enumerate(self.lines, start=1)
            if line.kind is LineKind.SALE
        }
        for line in self.lines:
            if line.kind is not LineKind.STORNO or line.cancels_line is None:
                continue
            target = netted[line.cancels_line]
            netted[line.cancels_line] = target.model_copy(
                update={
                    "quantity": target.quantity + line.quantity,
                    "printed_amount": target.printed_amount + line.printed_amount,
                    "included_discount": target.included_discount + line.included_discount,
                    "separate_discount": target.separate_discount + line.separate_discount,
                }
            )

        stored: list[ReceiptLine] = []
        for line in netted.values():
            summed = (
                line.quantity,
                line.printed_amount,
                line.included_discount,
                line.separate_discount,
            )
            if any(value < 0 for value in summed):
                raise ValueError(f"{line.printed_text!r} is cancelled beyond what was bought")
            if line.effective_amount < 0:
                raise ValueError(f"{line.printed_text!r} has a separate discount above its price")
            if line.quantity == 0:
                if line.printed_amount or line.included_discount or line.separate_discount:
                    raise ValueError(f"{line.printed_text!r} is netted to zero but keeps money")
                continue
            stored.append(line)
        if not stored:
            raise ValueError("receipt holds no purchased lines")
        return stored


class ReceiptSource(BaseModel):
    """Where a receipt came from. A new messenger or a file adds a kind, not a migration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SourceKind
    ref: str = Field(min_length=1)
    buyer_name: str = Field(min_length=1)


def telegram_source(chat_id: int, message_id: int, buyer_name: str) -> ReceiptSource:
    return ReceiptSource(
        kind=SourceKind.TELEGRAM,
        ref=f"{chat_id}:{message_id}",
        buyer_name=buyer_name,
    )


def zagreb_to_utc(naive: datetime) -> datetime:
    """Converts a Zagreb wall-clock time to UTC, to the minute, as the dedup key needs it.

    The ambiguous autumn hour takes the first (summer) offset, and a time skipped by the spring
    change takes the winter offset: Python's default fold=0 does both.
    """
    if naive.tzinfo is not None:
        raise ValueError("zagreb_to_utc takes a naive wall-clock time")
    local = naive.replace(second=0, microsecond=0, tzinfo=STORE_TIMEZONE)
    return local.astimezone(UTC)


def check_consistency(receipt: NormalizedReceipt) -> Decimal | None:
    """The signed difference between printed lines and payments, when it exceeds the tolerance.

    Storno and return lines count here, so the check sees the whole printed receipt.
    """
    lines_total = sum((line.effective_amount for line in receipt.lines), Decimal(0))
    settlements_total = sum((s.amount for s in receipt.settlements), Decimal(0))
    difference = lines_total - settlements_total
    return difference if abs(difference) > TOLERANCE else None


def check_total(receipt: NormalizedReceipt) -> Decimal | None:
    """The signed difference between the printed total and card plus cash, past the tolerance."""
    paid = sum(
        (
            s.amount
            for s in receipt.settlements
            if s.kind in (SettlementKind.CARD, SettlementKind.CASH)
        ),
        Decimal(0),
    )
    difference = receipt.total - paid
    return difference if abs(difference) > TOLERANCE else None
