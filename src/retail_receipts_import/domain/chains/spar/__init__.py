"""The Spar chain plug-in; Interspar receipts are Spar's too."""

from dataclasses import dataclass

from pydantic import BaseModel

from retail_receipts_import.domain.chains.spar.normalize import normalize
from retail_receipts_import.domain.chains.spar.prompt import PASS2_PROMPT
from retail_receipts_import.domain.chains.spar.schema import SparPass2
from retail_receipts_import.domain.receipt import NormalizedReceipt


@dataclass(frozen=True)
class SparPlugin:
    chain_id: str = "spar"
    pass2_prompt: str = PASS2_PROMPT
    pass2_schema: type[BaseModel] = SparPass2

    def normalize(self, response: str) -> NormalizedReceipt:
        # The chain comes from this plug-in's own key, never from what the model printed.
        return normalize(response, self.chain_id)


SPAR = SparPlugin()
