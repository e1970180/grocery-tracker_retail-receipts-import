"""What Gemini returns for a DM receipt: printed values only, as printed strings.

Strings and not numbers, so no amount passes through a float on its way to Decimal. No field
asks for the card slip: card numbers and terminal ids must never leave the document.
"""

from pydantic import BaseModel, Field


class DmLine(BaseModel):
    """Raw printed line item extracted from a DM receipt."""

    text: str = Field(description="Item name, or 'STORNO RETKA' if printed on its own line.")
    quantity: str | None = Field(
        default=None,
        description=(
            "Printed quantity such as '1', '2', or '-1' on a storno row; null on 'STORNO RETKA'."
        ),
    )
    unit_price: str | None = Field(
        default=None,
        description=(
            "Printed unit price such as '7,90', '1,10', or '-1,10'; null on 'STORNO RETKA'."
        ),
    )
    amount: str = Field(
        default="0,00",
        description="Printed line amount such as '7,90', '-1,10', or '0,00' on 'STORNO RETKA'.",
    )


class DmPayment(BaseModel):
    """Raw printed settlement or payment entry extracted from a DM receipt."""

    text: str = Field(
        description=(
            "Printed payment row label, such as 'MASTERCARD EUR', 'GOTOVINA EUR', "
            "or 'Povrat novaca EUR'."
        )
    )
    amount: str = Field(
        description="Printed payment amount signed as printed, such as '-15,80', '-4,00', '0,75'."
    )


class DmPass2(BaseModel):
    """Structured pass-2 extraction schema for DM receipts."""

    seller_oib: str | None = Field(
        default=None, description="Company OIB from the receipt header (11 digits next to 'OIB:')."
    )
    store_address: str | None = Field(
        default=None,
        description=(
            "The specific shop address line (e.g. 'Ulica Vice Vukova 6, 10000 ZAGREB') if printed "
            "above the head office, else null. Never the head office '10090 ZAGREB, Kovinska 5a'."
        ),
    )
    receipt_number: str | None = Field(
        default=None,
        description="Value after 'Broj računa:' or 'Br. računa:' as printed, e.g. '9619/K05F/5'.",
    )
    purchase_date: str = Field(
        description="Purchase date from the header line above the receipt number, as DD.MM.YYYY."
    )
    purchase_time: str = Field(
        description="Purchase time from the header line above the receipt number, as HH:MM."
    )
    total: str = Field(description="The 'Ukupno' amount.")
    lines: list[DmLine]
    payments: list[DmPayment]
