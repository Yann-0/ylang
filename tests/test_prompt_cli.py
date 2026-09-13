"""CLI tests for ``ylang prompts``."""

from __future__ import annotations

from pathlib import Path

import pytest

from ylang.cli.prompts import run_prompts_cli
from ylang.importer import import_into_library
from ylang.importer.refresh import open_source_store
from ylang.library import open_library

SAMPLE_CSV = Path(__file__).parent / "fixtures" / "sample_prompts.csv"


def test_prompts_sources_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "ylang.db"
    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    assert run_prompts_cli(["sources", "list"]) == 0
    out = capsys.readouterr().out
    assert "prompts-chat" in out
    assert "github-awesome-copilot" in out
    assert "fabric-patterns" in out


def test_prompts_candidates_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "ylang.db"
    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    import_into_library(db_path, csv_path=SAMPLE_CSV)
    assert run_prompts_cli(["candidates", "list"]) == 0
    listed = capsys.readouterr().out
    assert "prompts-chat:character" in listed
    assert run_prompts_cli(["candidates", "show", "prompts-chat:character"]) == 0
    assert run_prompts_cli(["candidates", "promote", "prompts-chat:character"]) == 0
    promoted = capsys.readouterr().out
    assert "promoted" in promoted
    library = open_library(db_path)
    try:
        template = library.recall("character")
        assert template is not None
        store = open_source_store(library)
        item = store.get_item("prompts-chat:character")
        assert item is not None
        assert item.candidate_state == "promoted"
        assert store.provenance_for_template("character")
    finally:
        library.close()
    assert run_prompts_cli(["candidates", "reject", "prompts-chat:plain-role"]) == 0
    assert run_prompts_cli(["metrics"]) == 0
    assert run_prompts_cli(["candidates", "evaluate", "prompts-chat:job-interviewer"]) == 0
    evaluated = capsys.readouterr().out
    assert "prompt-candidate:" in evaluated
    assert '"current_injections"' in evaluated


def test_prompts_cannot_auto_promote_via_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "ylang.db"
    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    import_into_library(db_path, csv_path=SAMPLE_CSV)
    library = open_library(db_path)
    try:
        assert library.recall("character") is None
    finally:
        library.close()
