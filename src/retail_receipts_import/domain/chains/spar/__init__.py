"""The Spar chain plug-in; Interspar receipts are Spar's too."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ValidationError

from retail_receipts_import.domain.chains.spar.normalize import normalize, normalize_pass1_time
from retail_receipts_import.domain.chains.spar.prompt import PASS2_PROMPT
from retail_receipts_import.domain.chains.spar.schema import SparPass2
from retail_receipts_import.domain.receipt import NormalizedReceipt


@dataclass(frozen=True)
class SparPlugin:
    chain_id: str = "spar"
    pass1_time_hint: str = 'Line "Vaša kupnja dana DD.MM.YYYY. u HH:MM sati" (never the card slip).'
    pass2_prompt: str = PASS2_PROMPT
    pass2_schema: type[BaseModel] = SparPass2

    def normalize_pass1_time(self, purchase_date: str, purchase_time: str) -> datetime | None:
        return normalize_pass1_time(purchase_date, purchase_time)

    def seller_oib(self, response: str) -> str | None:
        # Read through the same model as the receipt, so the guard sees the payload it guards.
        try:
            oib = SparPass2.model_validate_json(response).seller_oib
        except ValidationError:
            return None
        return (oib or "").strip() or None

    def normalize(self, response: str) -> NormalizedReceipt:
        # The chain comes from this plug-in's own key, never from what the model printed.
        return normalize(response, self.chain_id)


SPAR = SparPlugin()
