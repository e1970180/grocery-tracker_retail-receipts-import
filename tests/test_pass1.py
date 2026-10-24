from retail_receipts_import.domain.chains import OTHER, UNREADABLE, KnownChain
from retail_receipts_import.domain.chains.pass1 import (
    build_pass1_prompt,
    create_pass1_schema,
    is_supported_chain,
)
from retail_receipts_import.domain.chains.registry import PLUGINS


def test_pass1_schema_restricts_chain_to_active_and_sentinels() -> None:
    schema_cls = create_pass1_schema(("spar", "dm"))
    json_schema = schema_cls.model_json_schema()
    chain_prop = json_schema["properties"]["chain"]
    assert set(chain_prop["enum"]) == {"spar", "dm", OTHER, UNREADABLE}
    assert set(json_schema["properties"].keys()) == {
        "chain",
        "store_name",
        "purchase_date",
        "purchase_time",
    }


def test_pass1_prompt_lists_aliases_and_time_hints() -> None:
    chains = (
        KnownChain("dm", "dm", ("DM", "dm"), ("94124811986",)),
        KnownChain("spar", "Spar", ("SPAR", "Spar", "INTERSPAR"), ("46108893754",)),
    )
    prompt = build_pass1_prompt(chains, PLUGINS)
    assert "spar (Spar): aliases: SPAR, Spar, INTERSPAR." in prompt
    assert "dm (dm): aliases: DM, dm." in prompt
    assert "Vaša kupnja dana" in prompt
    assert OTHER in prompt
    assert UNREADABLE in prompt


def test_is_supported_chain() -> None:
    active = {"spar", "kaufland"}
    assert is_supported_chain("spar", active, PLUGINS) is True
    assert is_supported_chain("kaufland", active, PLUGINS) is False
    assert is_supported_chain("dm", active, PLUGINS) is False
    assert is_supported_chain(OTHER, active, PLUGINS) is False
    assert is_supported_chain(UNREADABLE, active, PLUGINS) is False
