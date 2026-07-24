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
        body="Older learned pattern body for {topic} with detailed guidance.",
        params=[],
    )
    save_learned_template(
        library,
        "learned-newer",
        name="Newer",
        body="Newer learned pattern body for {topic} with detailed guidance.",
        params=[],
    )
    results = select_learned_templates(library, limit=1)
    assert len(results) == 1
    assert results[0].template_id == "learned-newer"


def test_select_reference_prompts_excludes_archived(library) -> None:
    library.save(
        "archived-ref",
        name="Archived Ref",
        body="archived body for grep",
        params=[],
        source="user",
        visibility="archived",
        tags=["grep"],
    )
    library.save(
        "active-ref",
        name="Active Ref",
        body="active body for grep",
        params=[],
        source="user",
        visibility="public",
        tags=["grep"],
    )
    results = select_reference_prompts(library, "run grep search", "grep", limit=3)
    ids = {item.template_id for item in results}
    assert "archived-ref" not in ids
    assert "active-ref" in ids


def test_select_reference_prompts_excludes_zero_accept(library) -> None:
    library.save(
        "bad-ref",
        name="Bad Ref",
        body="bad grep prompt",
        params=[],
        source="user",
        visibility="public",
        tags=["grep"],
    )
    effectiveness = {"bad-ref": 0.0}
    results = select_reference_prompts(
        library,
        "run grep search",
        "grep",
        limit=3,
        effectiveness=effectiveness,
    )
    assert all(item.template_id != "bad-ref" for item in results)


def test_select_learned_templates_excludes_zero_accept(library) -> None:
    from ylang.library.retrieval import select_learned_templates
    from ylang.library.store import save_learned_template

    save_learned_template(
        library,
        "learned-bad",
        name="Bad Learned",
        body="Bad learned pattern body for {topic} with low acceptance rate.",
        params=[],
    )
    results = select_learned_templates(
        library,
        limit=3,
        effectiveness={"learned-bad": 0.0},
    )
    assert all(item.template_id != "learned-bad" for item in results)


def test_select_learned_templates_excludes_zero_accept_from_store(
    library, tmp_path: Path
) -> None:
    """Store-backed blocklist excludes templates even without effectiveness dict."""
    from datetime import datetime, timezone

    from ylang.core.stores import open_stores
    from ylang.library.retrieval import select_learned_templates
    from ylang.library.store import save_learned_template

    stores = open_stores(tmp_path / "usage.db")
    try:
        save_learned_template(
            library,
            "learned-noisy",
            name="Noisy Learned",
            body="Noisy learned pattern body for {topic} with low acceptance rate.",
            params=[],
        )
        now = datetime.now(timezone.utc)
        for _ in range(43):
            stores.store.write_usage(
                surface="mcp",
                activity="improve:agent",
                model_used="test/model",
                prompt_tokens=10,
                cost=0.01,
                improver_fired=True,
                improver_accepted=False,
                improver_validated=True,
                improver_changed=True,
                improver_context_templates="learned-noisy",
                latency_ms=50,
                success=True,
                timestamp=now,
            )
        results = select_learned_templates(
            library,
            limit=3,
            effectiveness=None,
            store=stores.store,
        )
        assert all(item.template_id != "learned-noisy" for item in results)
    finally:
        stores.close()


def test_select_reference_prompts_excludes_zero_accept_from_store(
    library, tmp_path: Path
) -> None:
    from datetime import datetime, timezone

    from ylang.core.stores import open_stores

    library.save(
        "public-zero",
        name="Zero Accept Public",
        body="zero accept grep prompt",
        params=[],
        source="user",
        visibility="public",
        tags=["grep"],
    )
    stores = open_stores(tmp_path / "usage-ref.db")
    try:
        now = datetime.now(timezone.utc)
        for _ in range(31):
            stores.store.write_usage(
                surface="mcp",
                activity="improve:agent",
                model_used="test/model",
                prompt_tokens=10,
                cost=0.01,
                improver_fired=True,
                improver_accepted=False,
                improver_validated=True,
                improver_changed=True,
                improver_context_templates="public-zero",
                latency_ms=50,
                success=True,
                timestamp=now,
            )
        results = select_reference_prompts(
            library,
            "run grep search",
            "grep",
            limit=3,
            store=stores.store,
        )
        assert all(item.template_id != "public-zero" for item in results)
    finally:
        stores.close()


def test_select_reference_prompts_boosts_preferred_ids(library) -> None:
    library.save(
        "weak-match",
        name="Weak Match",
        body="generic body",
        params=[],
        source="user",
        visibility="public",
        tags=["other"],
    )
    library.save(
        "fashion-portrait",
        name="Fashion Portrait",
        body="fashion portrait photography prompt",
        params=[],
        source="user",
        visibility="public",
        tags=["other"],
    )
    results = select_reference_prompts(
        library,
        "unrelated coding task about databases",
        "edit_file",
        limit=1,
        preferred_ids=frozenset({"fashion-portrait"}),
    )
    assert results
    assert results[0].template_id == "fashion-portrait"


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
