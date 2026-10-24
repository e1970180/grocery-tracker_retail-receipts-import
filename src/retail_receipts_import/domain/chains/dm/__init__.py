"""The DM chain plug-in."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ValidationError

from retail_receipts_import.domain.chains.dm.normalize import normalize, normalize_pass1_time
from retail_receipts_import.domain.chains.dm.prompt import PASS2_PROMPT
from retail_receipts_import.domain.chains.dm.schema import DmPass2
from retail_receipts_import.domain.receipt import NormalizedReceipt


@dataclass(frozen=True)
class DmPlugin:
    """Chain extraction plugin for dm-drogerie markt receipts."""

    chain_id: str = "dm"
    pass1_time_hint: str = (
        'Header line "DD.MM.YYYY HH:MM" above the receipt number (never the card slip).'
    )
    pass2_prompt: str = PASS2_PROMPT
    pass2_schema: type[BaseModel] = DmPass2

    def normalize_pass1_time(self, purchase_date: str, purchase_time: str) -> datetime | None:
        """Converts DM pass-1 printed date and time strings to UTC."""
        return normalize_pass1_time(purchase_date, purchase_time)

    def seller_oib(self, response: str) -> str | None:
        """Extracts the seller OIB tax identification number from pass-2 response JSON."""
        # Read through the same model as the receipt, so the guard sees the payload it guards.
        try:
            oib = DmPass2.model_validate_json(response).seller_oib
        except ValidationError:
            return None
        return (oib or "").strip() or None

    def normalize(self, response: str) -> NormalizedReceipt:
        """Parses and normalizes pass-2 JSON into canonical NormalizedReceipt."""
        # The chain comes from this plug-in's own key, never from what the model printed.
        return normalize(response, self.chain_id)


DM = DmPlugin()
