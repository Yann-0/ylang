"""Tests for template archive hygiene helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ylang.core.db import open_connection
from ylang.core.migrations import run_migrations
from ylang.library import open_library
from ylang.library.hygiene import (
    archive_low_effectiveness_templates,
    archive_template,
    archive_unused_public_templates,
    eligible_unused_public_template_ids,
    eligible_zero_accept_template_ids,
)
from ylang.usage.store import UsageStore


@pytest.fixture
def library(tmp_path: Path):
    lib = open_library(tmp_path / "library.db")
    yield lib
    lib.close()


def _write_usage(
    store: UsageStore,
    *,
    templates: str,
    accepted: bool,
) -> None:
    store.write_usage(
        surface="mcp",
        activity="improve:agent",
        model_used="test/model",
        prompt_tokens=10,
        cost=0.0,
        improver_fired=True,
        improver_accepted=accepted,
        latency_ms=1,
        success=True,
        timestamp=datetime.now(timezone.utc),
        improver_context_templates=templates,
        improver_validated=True,
        improver_changed=True,
        cursor_mode="agent",
    )


def test_archive_unused_public_templates(library, tmp_path: Path) -> None:
    library.save(
        "unused-public",
        name="Unused",
        body="body",
        params=[],
        source="user",
        visibility="public",
    )
    connection = open_connection(tmp_path / "usage.db")
    store = UsageStore(connection)
    store._ensure_schema()
    archived = archive_unused_public_templates(library, store)
    assert archived == ["unused-public"]
    assert library.recall("unused-public").visibility == "archived"


def test_archive_low_effectiveness_learned_zero_accept(
    library,
    tmp_path: Path,
) -> None:
    from ylang.library.store import save_learned_template

    save_learned_template(
        library,
        "learned-zero",
        name="Zero",
        body="Zero accept learned pattern body for {topic} with low acceptance.",
        params=[],
    )
    connection = open_connection(tmp_path / "usage-zero.db")
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    for _ in range(3):
        _write_usage(store, templates="learned-zero", accepted=False)

    archived = archive_low_effectiveness_templates(library, store, min_samples=3)
    assert "learned-zero" in archived
    assert library.recall("learned-zero").visibility == "archived"


def test_eligible_unused_public_template_ids(library) -> None:
    library.save(
        "idle-public",
        name="Idle",
        body="body",
        params=[],
        source="user",
        visibility="public",
    )
    eligible = eligible_unused_public_template_ids(
        library,
        {"idle-public": 0, "summarize": 5},
    )
    assert eligible == ["idle-public"]
    assert archive_template(library, "summarize") is False


def test_eligible_zero_accept_template_ids(library, tmp_path: Path) -> None:
    library.save(
        "toxic-user",
        name="Toxic",
        body="body for toxic template",
        params=[],
        source="user",
        visibility="private",
    )
    library.save(
        "healthy-user",
        name="Healthy",
        body="body for healthy template",
        params=[],
        source="user",
        visibility="private",
    )
    connection = open_connection(tmp_path / "usage-toxic.db")
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    for _ in range(3):
        _write_usage(store, templates="toxic-user", accepted=False)
        _write_usage(store, templates="healthy-user", accepted=True)

    eligible = eligible_zero_accept_template_ids(library, store, min_samples=3)
    assert eligible == ["toxic-user"]
    assert archive_template(library, "toxic-user") is True
    assert eligible_zero_accept_template_ids(library, store, min_samples=3) == []
