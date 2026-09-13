"""Tests for CSV conversion and candidate import (no live network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ylang.importer import import_into_library
from ylang.importer.convert import convert_rows, normalize_body, parse_csv_rows, slugify
from ylang.importer.refresh import open_source_store
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


def test_import_into_library_creates_candidates_not_templates(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    result = import_into_library(db_path, csv_path=SAMPLE_CSV)
    assert result.ok
    assert result.imported == 3
    assert result.skipped == 0

    library = open_library(db_path)
    try:
        assert library.recall("character") is None
        store = open_source_store(library)
        item = store.get_item("prompts-chat:character")
        assert item is not None
        assert item.candidate_state == "candidate_new"
        assert item.source_id == "prompts-chat"
        job = store.get_item("prompts-chat:job-interviewer")
        assert job is not None
        assert "{position}" in job.body
        seeds = {row.template_id for row in library.list(source="seed")}
        assert "summarize" in seeds
        assert "character" not in ids_from_library(library)
    finally:
        library.close()


def ids_from_library(library: object) -> set[str]:
    return {item.template_id for item in library.list(include_archived=True)}  # type: ignore[union-attr]


def test_import_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    first = import_into_library(db_path, csv_path=SAMPLE_CSV)
    second = import_into_library(db_path, csv_path=SAMPLE_CSV)
    assert first.imported == 3
    assert second.imported == 0
    assert second.skipped == 3


def test_import_does_not_overwrite_existing_seed_template(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    library = open_library(db_path)
    library.close()

    custom_csv = tmp_path / "summarize.csv"
    custom_csv.write_text(
        'act,prompt\nSummarize,"Summarize this: {text}"\n',
        encoding="utf-8",
    )
    result = import_into_library(db_path, csv_path=custom_csv)
    assert result.imported == 1
    library = open_library(db_path)
    try:
        seed = library.recall("summarize")
        assert seed is not None
        assert seed.source == "seed"
        assert "Summarize the following text" in seed.body
        store = open_source_store(library)
        item = store.get_item("prompts-chat:summarize")
        assert item is not None
        assert item.candidate_state == "candidate_new"
    finally:
        library.close()


def test_parse_csv_requires_columns() -> None:
    with pytest.raises(ValueError, match="act and prompt"):
        parse_csv_rows("name,body\nfoo,bar\n")


def test_manual_url_is_not_scheduled_source(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    result = import_into_library(
        db_path,
        url=None,
        csv_text=SAMPLE_CSV.read_text(encoding="utf-8"),
    )
    library = open_library(db_path)
    try:
        store = open_source_store(library)
        if result.source_id == "prompts-chat":
            source = store.get_source("prompts-chat")
            assert source is not None
            assert source.enabled is False
        manual = store.get_source("manual-import")
        assert manual is not None
        assert manual.enabled is False
    finally:
        library.close()
