"""Recorded Spar responses against their hand-derived records, offline.

Each case is `tests/fixtures/spar/<last 4 digits>/` with the recorded `pass2.json` and the
owner-confirmed `expected.json`. With no case recorded yet, the parametrized test is skipped.
"""

import re
from pathlib import Path
from typing import Any

import pytest

from retail_receipts_import.domain.chains.registry import PLUGINS
from retail_receipts_import.domain.chains.spar.schema import SparPass2
from retail_receipts_import.domain.receipt import NormalizedReceipt, check_consistency, check_total

FIXTURES = Path(__file__).parent / "fixtures"
CASES = sorted(
    path.parent
    for path in (FIXTURES / "spar").glob("*/pass2.json")
    if (path.parent / "expected.json").is_file()
)
# Card slip fields and card numbers, masked or not; none of them may be committed.
CARD_DATA = re.compile(r"\b(?:TID|MID|RRN|AID)\b|\d{4,6}\*{4,}\d{4}|(?<!\d)\d{13,19}(?!\d)")


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_recorded_response_gives_the_confirmed_record(case: Path) -> None:
    receipt = PLUGINS["spar"].normalize((case / "pass2.json").read_text(encoding="utf-8"))
    expected = NormalizedReceipt.model_validate_json(
        (case / "expected.json").read_text(encoding="utf-8")
    )
    assert receipt == expected
    assert check_consistency(receipt) is None
    assert check_total(receipt) is None


def test_fixtures_hold_no_card_data() -> None:
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            assert CARD_DATA.search(path.read_text(encoding="utf-8")) is None, path


def _property_names(schema: Any) -> list[str]:
    if isinstance(schema, dict):
        own = list(schema.get("properties", {}))
        return own + [name for value in schema.values() for name in _property_names(value)]
    if isinstance(schema, list):
        return [name for value in schema for name in _property_names(value)]
    return []


def test_schema_asks_for_no_card_or_terminal_field() -> None:
    names = _property_names(SparPass2.model_json_schema())
    assert "payments" in names
    for name in names:
        assert not re.search(r"card|pan|tid|mid|rrn|terminal|chain", name), name


def test_registry_keys_are_the_plugins_own_ids() -> None:
    assert "spar" in PLUGINS
    for chain_id, plugin in PLUGINS.items():
        assert plugin.chain_id == chain_id
