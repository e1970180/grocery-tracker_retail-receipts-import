"""The chain plug-ins this service can extract, keyed by the reference chain id.

A chain id missing here is unsupported, so this mapping is the only list of supported chains.
"""

from typing import Protocol

from pydantic import BaseModel

from retail_receipts_import.domain.chains.spar import SPAR
from retail_receipts_import.domain.receipt import NormalizedReceipt


class ChainPlugin(Protocol):
    @property
    def chain_id(self) -> str: ...

    @property
    def pass2_prompt(self) -> str: ...

    @property
    def pass2_schema(self) -> type[BaseModel]: ...

    def normalize(self, response: str) -> NormalizedReceipt:
        """Builds the receipt from the raw pass-2 JSON, or raises `UnreadableReceipt`."""
        ...


PLUGINS: dict[str, ChainPlugin] = {plugin.chain_id: plugin for plugin in (SPAR,)}
