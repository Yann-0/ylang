"""Tests for the public prompt importer."""

from __future__ import annotations

from pathlib import Path

import pytest

from ylang.importer import import_into_library
from ylang.importer.convert import convert_rows, normalize_body, parse_csv_rows, slugify
from ylang.library import open_library

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_CSV = FIXTURES / "sample_prompts.csv"


def test_slugify() -> None:
    assert slugify("Linux Terminal") == "linux-terminal"
    assert slugify("  Hello!!! World  ") == "hello-world"


def test_normalize_body_extracts_brace_params() -> None:
    body, params = normalize_body("Act like {character} from {series}.")
    assert body == "Act like {character} from {series}."
    assert {p.name for p in params} == {"character", "series"}


def test_normalize_body_converts_dollar_vars() -> None:
    body, params = normalize_body("Role: ${Position:Engineer}")
    assert body == "Role: {position}"
    assert len(params) == 1
    assert params[0].name == "position"
    assert params[0].default == "Engineer"


def test_normalize_body_fallback_input_param() -> None:
    _body, params = normalize_body("You are a helpful assistant.")
    assert len(params) == 1
    assert params[0].name == "input"


def test_parse_and_convert_fixture() -> None:
    rows = parse_csv_rows(SAMPLE_CSV.read_text(encoding="utf-8"))
    prompts = convert_rows(rows)
    assert len(prompts) == 3
    by_id = {p.template_id: p for p in prompts}
    assert "character" in by_id
    assert "job-interviewer" in by_id
    assert "plain-role" in by_id
    assert "{position}" in by_id["job-interviewer"].body


def test_import_into_library(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    result = import_into_library(db_path, csv_path=SAMPLE_CSV)
    assert result.imported == 3
    assert result.skipped == 0

    library = open_library(db_path)
    try:
        character = library.recall("character")
        assert character is not None
        assert character.source == "seed"
        assert character.name == "Character"
        assert "character" in {p.name for p in character.params}

        job = library.recall("job-interviewer")
        assert job is not None
        rendered = library.render("job-interviewer", {"position": "Designer"})
        assert "Designer" in rendered
    finally:
        library.close()


def test_import_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    first = import_into_library(db_path, csv_path=SAMPLE_CSV)
    second = import_into_library(db_path, csv_path=SAMPLE_CSV)
    assert first.imported == 3
    assert second.imported == 0
    assert second.skipped == 3


def test_import_skips_existing_seed_template(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    library = open_library(db_path)
    library.close()

    custom_csv = tmp_path / "summarize.csv"
    custom_csv.write_text(
        'act,prompt\nSummarize,"Summarize this: {text}"\n',
        encoding="utf-8",
    )
    result = import_into_library(db_path, csv_path=custom_csv)
    assert result.imported == 0
    assert result.skipped == 1


def test_parse_csv_requires_columns() -> None:
    with pytest.raises(ValueError, match="act and prompt"):
        parse_csv_rows("name,body\nfoo,bar\n")
