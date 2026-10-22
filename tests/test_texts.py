from pathlib import Path

import pytest

from retail_receipts_import.app.texts import TextsError, load_texts
from retail_receipts_import.domain.outcomes import FailureReason, Outcome

SHIPPED = Path(__file__).resolve().parents[1] / "texts" / "messages.toml"


def _variant(tmp_path: Path, old: str, new: str) -> Path:
    text = SHIPPED.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "messages.toml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def test_shipped_texts_file_is_complete() -> None:
    texts = load_texts(SHIPPED)
    assert texts.sender_messages[Outcome.DUPLICATE] == "Данный чек уже внесен в систему"
    assert set(texts.reactions) == {
        Outcome.STORED,
        Outcome.DUPLICATE,
        Outcome.FAILED,
        Outcome.IN_PROGRESS,
        Outcome.NOT_ACCEPTED,
    }
    for reason in FailureReason:
        assert texts.sender_messages[reason]
        assert texts.admin_messages[reason]


def test_missing_key_is_refused_by_name(tmp_path: Path) -> None:
    path = _variant(tmp_path, 'no_valid_result = "Не удалось', 'other = "Не удалось')
    with pytest.raises(TextsError, match=r"missing keys sender_messages\.no_valid_result"):
        load_texts(path)


def test_missing_table_is_refused(tmp_path: Path) -> None:
    path = _variant(tmp_path, "[admin_messages]", "[admin]")
    with pytest.raises(TextsError, match=r"missing table \[admin_messages\]"):
        load_texts(path)


def test_unknown_key_is_refused(tmp_path: Path) -> None:
    path = _variant(tmp_path, "[reactions]", '[reactions]\nstoredd = "👍"')
    with pytest.raises(TextsError, match=r"unknown keys reactions\.storedd"):
        load_texts(path)


def test_disallowed_reaction_emoji_is_refused_by_key(tmp_path: Path) -> None:
    path = _variant(tmp_path, 'in_progress = "👀"', 'in_progress = "⏳"')
    with pytest.raises(TextsError, match=r"reactions\.in_progress"):
        load_texts(path)


def test_emoji_with_variation_selector_is_refused(tmp_path: Path) -> None:
    path = _variant(tmp_path, 'stored = "👍"', 'stored = "❤️"')
    with pytest.raises(TextsError, match=r"reactions\.stored"):
        load_texts(path)


def test_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TextsError, match="texts file"):
        load_texts(tmp_path / "absent.toml")
