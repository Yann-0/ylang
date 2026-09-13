"""Tests for versioned improver context template refs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ylang.cli.prompts import LARGE_CATALOG_WARN_THRESHOLD, _warn_large_catalog
from ylang.core.engine import Engine
from ylang.improver.context import ImproveContext
from ylang.improver.improver import Improver
from ylang.importer.evaluate import measure_template
from ylang.importer.source_types import RefreshSummary
from ylang.library import open_library
from ylang.library.store import Library
from ylang.usage.store import UsageStore, UsageWindow, open_store
from ylang.usage.template_refs import (
    format_template_ref,
    format_template_refs,
    parse_template_ref,
    parse_template_refs,
    template_ids_from_refs,
)


def test_format_and_parse_template_refs() -> None:
    assert format_template_ref("character", 3) == "character@3"
    assert format_template_ref("character", None) == "character"
    assert parse_template_ref("character@3") == ("character", 3)
    assert parse_template_ref("character") == ("character", None)
    assert parse_template_ref("weird@x") == ("weird@x", None)
    encoded = format_template_refs([("a", 1), ("b", None), ("c", 2)])
    assert encoded == "a@1,b,c@2"
    assert parse_template_refs(encoded) == [("a", 1), ("b", None), ("c", 2)]
    assert template_ids_from_refs(encoded) == ["a", "b", "c"]


def _mock_litellm(improved: str = "hello") -> MagicMock:
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps({"improved": improved, "changes": []})
            )
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}
    return mock_response


def _usage_on(library: Library) -> UsageStore:
    store = UsageStore(library._connection)
    store._ensure_schema()
    return store


def test_improver_writes_id_at_version(tmp_path: Path) -> None:
    store = open_store(tmp_path / "usage.db")
    engine = Engine(store, surface="test")
    improver = Improver(engine)
    context = ImproveContext(
        reference_prompts_block="### Character\nbody",
        reference_template_ids=("character",),
        reference_template_refs=(("character", 2),),
    )
    with patch("ylang.core.engine.litellm.completion", return_value=_mock_litellm()):
        improver.improve(
            "hello",
            "edit_file",
            model="test-model",
            context=context,
        )
    rows = store.recall_usage(UsageWindow.last_hours(1))
    assert rows
    latest = rows[-1]
    assert latest.improver_context_templates == "character@2"
    assert latest.template_version == 2


def test_multi_template_does_not_set_scalar_or_cross_attribute(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path / "usage.db")
    engine = Engine(store, surface="test")
    improver = Improver(engine)
    context = ImproveContext(
        reference_prompts_block="### A\nbody\n### B\nbody",
        reference_template_ids=("a", "b"),
        reference_template_refs=(("a", 1), ("b", 3)),
    )
    with patch("ylang.core.engine.litellm.completion", return_value=_mock_litellm()):
        improver.improve(
            "hello",
            "edit_file",
            model="test-model",
            context=context,
        )
    latest = store.recall_usage(UsageWindow.last_hours(1))[-1]
    assert latest.improver_context_templates == "a@1,b@3"
    assert latest.template_version is None

    library = open_library(tmp_path / "lib.db")
    library.save("a", name="A", body="a", params=[], source="user")
    library.save("b", name="B", body="b", params=[], source="user")
    shared = _usage_on(library)
    now = datetime.now(timezone.utc)
    shared.write_usage(
        surface="mcp",
        activity="improve:agent",
        model_used="test/model",
        prompt_tokens=1,
        cost=0.01,
        improver_fired=True,
        improver_accepted=True,
        latency_ms=10,
        success=True,
        timestamp=now,
        improver_context_templates="a@1,b@3",
        improver_validated=True,
        improver_changed=True,
    )
    snap_a = measure_template(
        library, shared, "a", version=1, since=now - timedelta(minutes=1)
    )
    snap_b_wrong = measure_template(
        library, shared, "b", version=1, since=now - timedelta(minutes=1)
    )
    snap_b_ok = measure_template(
        library, shared, "b", version=3, since=now - timedelta(minutes=1)
    )
    assert snap_a.attribution == "versioned"
    assert snap_a.injections == 1
    assert snap_b_wrong.injections == 0
    assert "other_template_versions" in snap_b_wrong.confounders
    assert snap_b_ok.injections == 1
    library.close()


def test_versioned_ref_counts_for_matching_version_only(tmp_path: Path) -> None:
    library = open_library(tmp_path / "lib.db")
    library.save("character", name="Character", body="v1", params=[], source="user")
    library.save("character", name="Character", body="v2", params=[], source="user")
    store = _usage_on(library)
    now = datetime.now(timezone.utc)
    store.write_usage(
        surface="mcp",
        activity="improve:agent",
        model_used="test/model",
        prompt_tokens=1,
        cost=0.01,
        improver_fired=True,
        improver_accepted=True,
        latency_ms=10,
        success=True,
        timestamp=now - timedelta(seconds=30),
        improver_context_templates="character@2",
        improver_validated=True,
        improver_changed=True,
    )
    store.write_usage(
        surface="mcp",
        activity="improve:agent",
        model_used="test/model",
        prompt_tokens=1,
        cost=0.01,
        improver_fired=True,
        improver_accepted=False,
        latency_ms=10,
        success=True,
        timestamp=now - timedelta(seconds=10),
        improver_context_templates="character",
        improver_validated=True,
        improver_changed=True,
    )
    v2 = measure_template(
        library, store, "character", version=2, since=now - timedelta(minutes=1)
    )
    assert v2.attribution == "versioned"
    assert v2.injections == 1
    assert v2.unversioned_events == 1
    library.close()


def test_large_catalog_warn(capsys: pytest.CaptureFixture[str]) -> None:
    summary = RefreshSummary(
        source_id="prompts-chat",
        status="success",
        revision_before=None,
        revision_after="sha",
        new=LARGE_CATALOG_WARN_THRESHOLD,
        changed=0,
        unchanged=0,
    )
    _warn_large_catalog(summary)
    err = capsys.readouterr().err
    assert "warning" in err
    assert "prompts-chat" in err
    assert str(LARGE_CATALOG_WARN_THRESHOLD) in err
    small = RefreshSummary(
        source_id="prompts-chat",
        status="success",
        revision_before=None,
        revision_after="sha",
        new=10,
    )
    _warn_large_catalog(small)
    assert capsys.readouterr().err == ""
