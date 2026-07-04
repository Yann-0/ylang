"""Tests for library reference prompt retrieval."""

from __future__ import annotations

from pathlib import Path

import pytest

from ylang.library import open_library
from ylang.library.retrieval import select_reference_prompts
from ylang.library.types import TemplateParam


@pytest.fixture
def library(tmp_path: Path):
    lib = open_library(tmp_path / "library.db")
    yield lib
    lib.close()


def test_select_reference_prompts_tool_tag_match(library) -> None:
    library.save(
        "edit-file-guide",
        name="Edit File Guide",
        body="Edit {file} carefully.",
        params=[TemplateParam(name="file", description="Path")],
        source="user",
        visibility="public",
        tags=["edit_file"],
    )
    results = select_reference_prompts(
        library,
        "fix bug in main.py",
        "edit_file",
        limit=3,
    )
    assert results
    assert results[0].template_id == "edit-file-guide"


def test_select_reference_prompts_prefers_public_on_tie(library) -> None:
    library.save(
        "private-match",
        name="Private Match",
        body="private body",
        params=[],
        source="user",
        visibility="private",
        tags=["grep"],
    )
    library.save(
        "public-match",
        name="Public Match",
        body="public body",
        params=[],
        source="user",
        visibility="public",
        tags=["grep"],
    )
    results = select_reference_prompts(library, "run grep search", "grep", limit=2)
    assert len(results) >= 2
    assert results[0].template_id == "public-match"


def test_select_reference_prompts_respects_char_budget(library) -> None:
    library.save(
        "huge-template",
        name="Huge",
        body="x" * 5000,
        params=[],
        source="user",
        visibility="public",
        tags=["analyze"],
    )
    library.save(
        "small-template",
        name="Small",
        body="short analyze prompt",
        params=[],
        source="user",
        visibility="public",
        tags=["analyze"],
    )
    results = select_reference_prompts(
        library,
        "analyze this code",
        "analyze",
        limit=3,
        max_chars=200,
    )
    ids = {item.template_id for item in results}
    assert "small-template" in ids
    assert "huge-template" not in ids


def test_select_learned_templates_by_recency(library) -> None:
    from ylang.library.retrieval import select_learned_templates
    from ylang.library.store import save_learned_template

    save_learned_template(
        library,
        "learned-older",
        name="Older",
        body="older pattern",
        params=[],
    )
    save_learned_template(
        library,
        "learned-newer",
        name="Newer",
        body="newer pattern",
        params=[],
    )
    results = select_learned_templates(library, limit=1)
    assert len(results) == 1
    assert results[0].template_id == "learned-newer"


def test_library_list_cache_invalidates_on_save(library) -> None:
    library.save(
        "cache-test",
        name="Cache Test",
        body="body",
        params=[],
        source="user",
        visibility="public",
        tags=["test"],
    )
    first = library.list()
    second = library.list()
    assert first is second
    library.save(
        "cache-test-2",
        name="Cache Test 2",
        body="body2",
        params=[],
        source="user",
        visibility="public",
        tags=["test"],
    )
    third = library.list()
    assert third is not first
    assert len(third) == len(first) + 1
