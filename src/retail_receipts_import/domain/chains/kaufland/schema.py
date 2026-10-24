"""What Gemini returns for a Kaufland receipt: printed values only, as printed strings.

Strings and not numbers, so no amount passes through a float on its way to Decimal. No field
asks for the card slip: card numbers and terminal ids must never leave the document.
"""

from pydantic import BaseModel, Field


class KauflandLine(BaseModel):
    """Raw printed line item extracted from a Kaufland receipt."""

    text: str = Field(
        description=(
            "Item name, discount text such as 'Kaufland Card%', 'Popust na kupnju', "
            "or 'Štedite ...'."
        )
    )
    quantity: str | None = Field(
        default=None, description="Printed quantity such as '1', '2' or '0,774'; null on discount."
    )
    unit: str | None = Field(default=None, description="'kg' on a weighed item, else null.")
    unit_price: str | None = Field(
        default=None, description="Printed price per piece or per kg; null on a discount."
    )
    amount: str = Field(
        description="Printed line amount such as '2,90', '-0,88', or saved EUR on a 'Štedite' row."
    )


class KauflandPayment(BaseModel):
    """Raw printed settlement or payment entry extracted from a Kaufland receipt."""

    text: str = Field(
        description="Printed payment row label, such as 'Kartica', 'Euro EUR', 'Za vratiti'."
    )
    amount: str = Field(description="Printed amount such as '4,99', '50,00', '6,33'.")


class KauflandPass2(BaseModel):
    """Structured pass-2 extraction schema for Kaufland receipts."""

    seller_oib: str | None = Field(
        default=None, description="Company OIB from the receipt header (11 digits)."
    )
    pj_line: str | None = Field(
        default=None, description="Value on the 'PJ' line as printed, e.g. 'PJ5230,Zagreb Blato'."
    )
    store_address: str | None = Field(
        default=None, description="The store address line under the PJ line."
    )
    receipt_number: str | None = Field(
        default=None, description="Value after 'Račun' as printed, e.g. '21833/5230/6'."
    )
    purchase_date: str = Field(description="Date beside 'Datum:', as DD.MM.YY or DD.MM.YYYY.")
    purchase_time: str = Field(description="Time beside 'Vrijeme', as HH:MM:SS or HH:MM.")
    total: str = Field(description="The 'Za platiti' amount.")
    lines: list[KauflandLine]
    payments: list[KauflandPayment]
    loyalty_card: str | None = Field(
        default=None, description="Masked card number after 'Kaufland Card:', e.g. 'xxxxx8265'."
    )
