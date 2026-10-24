"""What Gemini returns for a Müller receipt: printed values only, as printed strings.

Strings and not numbers, so no amount passes through a float on its way to Decimal. No field
asks for the card slip: card numbers and terminal ids must never leave the document.
"""

from pydantic import BaseModel, Field


class MuellerLine(BaseModel):
    text: str = Field(description="Item name as printed.")
    quantity: str | None = Field(
        default=None,
        description=(
            "Printed quantity (Kom), such as '1', '2'; null on POVRATNA NAKNADA if missing."
        ),
    )
    unit_price: str | None = Field(
        default=None,
        description="Printed unit price (Cijena), such as '11,99', '0,99', '0,10'.",
    )
    discount: str | None = Field(
        default=None,
        description=(
            "Printed item discount (Popust) if present, such as '-0,10'; null if not discounted."
        ),
    )
    amount: str = Field(
        description=(
            "Printed line amount (Iznos) including any glued VAT letter, such as "
            "'11,99a', '0,89a', '0,10b'."
        ),
    )
    discount_note: str | None = Field(
        default=None,
        description=(
            "Discount description text printed below the discounted item row, such as "
            "'Coupon 0,89 Blink'; null if none."
        ),
    )


class MuellerPayment(BaseModel):
    text: str = Field(
        description=(
            "Printed payment row label, such as 'PLACANJE KARTICOM EUR', 'GOTOVINA EUR', "
            "'POVRAT NOVCA EUR', or 'Müller bodovi EUR'."
        )
    )
    amount: str = Field(
        description=(
            "Printed payment amount signed as printed, without currency, such as "
            "'3,28', '50,00', '-34,40', '3,01'."
        )
    )


class MuellerPass2(BaseModel):
    seller_oib: str | None = Field(
        default=None,
        description="Company OIB from the footer next to 'OIB:' (11 digits).",
    )
    store_name: str | None = Field(
        default=None,
        description="Shop name line under the company address, e.g. 'Zagreb EKZ Arena'.",
    )
    store_address: str | None = Field(
        default=None,
        description=(
            "Specific store address line under the shop name without the phone, e.g. "
            "'Ulica Vice Vukova 6, 10000 Zagreb'."
        ),
    )
    receipt_number: str | None = Field(
        default=None,
        description="Value after 'RB :' as printed, e.g. '18101/4981/3'.",
    )
    purchase_date: str = Field(
        description="Purchase date from the footer line beside the code, as DD.MM.YYYY.",
    )
    purchase_time: str = Field(
        description="Purchase time from the footer line beside the code, as HH:MM.",
    )
    amount_to_pay: str = Field(
        description="The 'ZA PLATITI' amount, e.g. '3,28'.",
    )
    lines: list[MuellerLine]
    payments: list[MuellerPayment]
