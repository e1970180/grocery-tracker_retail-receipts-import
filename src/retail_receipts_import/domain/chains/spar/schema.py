"""What Gemini returns for a Spar receipt: printed values only, as printed strings.

Strings and not numbers, so no amount passes through a float on its way to Decimal. No field
asks for the card slip: card numbers and terminal ids must never leave the PDF.
"""

from pydantic import BaseModel, Field


class SparLine(BaseModel):
    """Raw printed line item extracted from a Spar receipt."""

    text: str = Field(description="Item name, or the discount text such as 'Joker 15%'.")
    quantity: str | None = Field(
        default=None, description="Printed quantity such as '2' or '0,326'; null on a discount."
    )
    unit: str | None = Field(default=None, description="'kg(N)' on a weighed item, else null.")
    unit_price: str | None = Field(
        default=None, description="Printed price per piece or per kg; null on a discount."
    )
    amount: str = Field(description="Printed line amount such as '1,98' or '-0,30'.")


class SparPayment(BaseModel):
    """Raw printed settlement or payment entry extracted from a Spar receipt."""

    text: str = Field(description="Printed payment row label, such as 'PLAĆANJE GOTOVINOM'.")
    amount: str = Field(description="Printed amount such as '50,00'.")


class SparPass2(BaseModel):
    """Structured pass-2 extraction schema for Spar receipts."""

    seller_oib: str | None = Field(
        default=None, description="Company OIB from the receipt header (11 digits)."
    )
    store_name: str = Field(description="Store line under the company OIB line.")
    store_address: str | None = Field(default=None, description="Line under the store line.")
    receipt_number: str | None = Field(
        default=None, description="Value after 'Broj računa:' as printed."
    )
    purchase_date: str = Field(description="Date from 'Vaša kupnja dana', as DD.MM.YYYY.")
    purchase_time: str = Field(description="Time from 'Vaša kupnja dana', as HH:MM.")
    total: str = Field(description="UKUPNO amount.")
    lines: list[SparLine]
    payments: list[SparPayment]
