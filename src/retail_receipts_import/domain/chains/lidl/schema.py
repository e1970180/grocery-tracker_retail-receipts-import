"""What Gemini returns for a Lidl receipt: printed values only, as printed strings.

Strings and not numbers, so no amount passes through a float on its way to Decimal. No field
asks for the card slip: card numbers and terminal ids must never leave the image.
"""

from pydantic import BaseModel, Field


class LidlLine(BaseModel):
    """Raw printed line item extracted from a Lidl receipt."""

    text: str = Field(
        description="Item name, or discount text such as 'POPUST 25%', 'Lidl akcija'."
    )
    quantity: str | None = Field(
        default=None, description="Printed quantity such as '1', '2' or '0,946'; null on discount."
    )
    unit: str | None = Field(default=None, description="'kg' on a weighed item, else null.")
    unit_price: str | None = Field(
        default=None, description="Printed price per piece or per kg; null on a discount."
    )
    amount: str = Field(description="Printed line amount such as '3,29', '-0,83', '0,00'.")


class LidlPayment(BaseModel):
    """Raw printed settlement or payment entry extracted from a Lidl receipt."""

    text: str = Field(description="Printed payment row label, such as 'Kartica', 'Novčanice'.")
    amount: str = Field(description="Printed amount such as '19,75', '100,00', '-57,03'.")


class LidlPass2(BaseModel):
    """Structured pass-2 extraction schema for Lidl receipts."""

    seller_oib: str | None = Field(
        default=None, description="Company OIB from the receipt header (11 digits)."
    )
    pj: str | None = Field(
        default=None, description="Value next to 'PJ:' as printed (e.g. '0269')."
    )
    ibr: str | None = Field(
        default=None, description="Value after 'IBR:' as printed (e.g. '0269/024832/05')."
    )
    store_address: str | None = Field(
        default=None, description="The store address line under the OIB / PJ line."
    )
    receipt_number: str | None = Field(
        default=None, description="Value after 'Br.rač.:' as printed."
    )
    purchase_date: str = Field(description="Date beside 'Datum:', as DD.MM.YYYY.")
    purchase_time: str = Field(description="Time beside 'Datum:', as HH:MM or HH:MM:SS.")
    total: str = Field(description="The 'za platiti' amount.")
    lines: list[LidlLine]
    payments: list[LidlPayment]
