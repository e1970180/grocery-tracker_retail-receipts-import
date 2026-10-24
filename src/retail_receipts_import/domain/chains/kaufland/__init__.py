"""The Kaufland chain plug-in."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ValidationError

from retail_receipts_import.domain.chains.kaufland.normalize import normalize, normalize_pass1_time
from retail_receipts_import.domain.chains.kaufland.prompt import PASS2_PROMPT
from retail_receipts_import.domain.chains.kaufland.schema import KauflandPass2
from retail_receipts_import.domain.receipt import NormalizedReceipt


@dataclass(frozen=True)
class KauflandPlugin:
    chain_id: str = "kaufland"
    pass1_time_hint: str = 'Line "Datum:DD.MM.YY VrijemeHH:MM:SS" (never the card slip).'
    pass2_prompt: str = PASS2_PROMPT
    pass2_schema: type[BaseModel] = KauflandPass2

    def normalize_pass1_time(self, purchase_date: str, purchase_time: str) -> datetime | None:
        return normalize_pass1_time(purchase_date, purchase_time)

    def seller_oib(self, response: str) -> str | None:
        # Read through the same model as the receipt, so the guard sees the payload it guards.
        try:
            oib = KauflandPass2.model_validate_json(response).seller_oib
        except ValidationError:
            return None
        return (oib or "").strip() or None

    def normalize(self, response: str) -> NormalizedReceipt:
        # The chain comes from this plug-in's own key, never from what the model printed.
        return normalize(response, self.chain_id)


KAUFLAND = KauflandPlugin()
