"""The chain plug-ins this service can extract, keyed by the reference chain id.

A chain id missing here is unsupported, so this mapping is the only list of supported chains.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from retail_receipts_import.domain.chains.dm import DM
from retail_receipts_import.domain.chains.kaufland import KAUFLAND
from retail_receipts_import.domain.chains.lidl import LIDL
from retail_receipts_import.domain.chains.mueller import MUELLER
from retail_receipts_import.domain.chains.spar import SPAR
from retail_receipts_import.domain.receipt import NormalizedReceipt


class ChainPlugin(Protocol):
    @property
    def chain_id(self) -> str: ...

    @property
    def pass1_time_hint(self) -> str: ...

    @property
    def pass2_prompt(self) -> str: ...

    @property
    def pass2_schema(self) -> type[BaseModel]: ...

    def normalize_pass1_time(self, purchase_date: str, purchase_time: str) -> datetime | None:
        """Converts pass-1 date and time strings to aware UTC, or None if unreadable."""
        ...

    def seller_oib(self, response: str) -> str | None:
        """Returns the printed seller OIB from the pass-2 JSON, or None if missing or unreadable."""
        ...

    def normalize(self, response: str) -> NormalizedReceipt:
        """Builds the receipt from the raw pass-2 JSON, or raises `UnreadableReceipt`."""
        ...


PLUGINS: dict[str, ChainPlugin] = {
    plugin.chain_id: plugin for plugin in (SPAR, LIDL, KAUFLAND, DM, MUELLER)
}
