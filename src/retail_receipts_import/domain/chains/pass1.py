"""Pass 1: chain detection and receipt header fields from the receipt image."""

from typing import Any, Literal, cast

from pydantic import BaseModel, Field, create_model

from retail_receipts_import.domain.chains import OTHER, UNREADABLE, KnownChain
from retail_receipts_import.domain.chains.registry import ChainPlugin


class Pass1Response(BaseModel):
    chain: str = Field(description="The detected retail grocery chain slug.")
    store_name: str | None = Field(
        default=None, description="Store or branch name printed on the receipt."
    )
    purchase_date: str | None = Field(
        default=None, description="Purchase date as printed (DD.MM.YYYY)."
    )
    purchase_time: str | None = Field(default=None, description="Purchase time as printed (HH:MM).")


def create_pass1_schema(active_chain_ids: tuple[str, ...]) -> type[Pass1Response]:
    """Built per receipt from the reference just read, so the model can only name a live chain."""
    allowed = (*active_chain_ids, OTHER, UNREADABLE)
    chain_type = cast(Any, Literal.__getitem__(allowed))
    return create_model(
        "DynamicPass1Response",
        __base__=Pass1Response,
        chain=(chain_type, Field(description="The detected retail grocery chain slug.")),
    )


def build_pass1_prompt(chains: tuple[KnownChain, ...], plugins: dict[str, ChainPlugin]) -> str:
    """Aliases are how chains are printed; the plug-in hints keep the model off card-slip times."""
    lines = [
        "Identify the retail grocery chain, store name, and purchase date and time "
        "from this receipt from Croatia.",
        "",
        "Classify the receipt into one of the following chains:",
    ]
    for chain in chains:
        chain_desc = f"- {chain.chain_id} ({chain.display_name})"
        if chain.aliases:
            chain_desc += f": aliases: {', '.join(chain.aliases)}."
        else:
            chain_desc += "."
        if plugin := plugins.get(chain.chain_id):
            chain_desc += f" Time hint: {plugin.pass1_time_hint}."
        lines.append(chain_desc)

    lines.extend(
        [
            f"- {OTHER}: use this if the receipt is from another store not listed above.",
            f"- {UNREADABLE}: use this if the image cannot be read, is blank, or is not a receipt.",
            "",
            "Fields to return:",
            "- chain: the chosen chain slug, exactly one of the options above.",
            "- store_name: the printed store or branch name as shown on the receipt.",
            "- purchase_date: printed purchase date, or null if unreadable.",
            "- purchase_time: printed purchase time, or null if unreadable.",
        ]
    )
    return "\n".join(lines) + "\n"


def is_supported_chain(
    chain_id: str, active_chain_ids: set[str], plugins: dict[str, ChainPlugin]
) -> bool:
    """Pass 2 needs a plug-in, and a withdrawn chain must not be extracted even if one exists."""
    return chain_id in active_chain_ids and chain_id in plugins
