"""Tests for improver analytics and optimization modules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ylang.core.db import open_connection
from ylang.core.migrations import run_migrations
from ylang.usage.feedback import FeedbackStore
from ylang.usage.improver_analytics import summarize_improver, template_effectiveness
from ylang.usage.optimizer import generate_optimization_suggestions
from ylang.usage.store import UsageStore, UsageWindow


def _write_improver_row(
    store: UsageStore,
    *,
    when: datetime,
    accepted: bool = False,
    validated: bool = True,
    changed: bool = True,
    templates: str | None = "seed-1",
    mode: str = "agent",
    rejection: str | None = None,
) -> None:
    store.write_usage(
        surface="mcp",
        activity=f"improve:{mode}",
        model_used="test/model",
        prompt_tokens=100,
        cost=0.01,
        improver_fired=True,
        improver_accepted=accepted,
        latency_ms=50,
        success=True,
        timestamp=when,
        improver_input_sample="fix the bug",
        improver_context_templates=templates,
        improver_validated=validated,
        improver_changed=changed,
        improver_rejection_reason=rejection,
        improver_task_class="implementation",
        cursor_mode=mode,
    )


def test_summarize_improver_funnel(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    now = datetime.now(timezone.utc)
    for index in range(4):
        _write_improver_row(
            store,
            when=now - timedelta(hours=index),
            accepted=index % 2 == 0,
        )
    _write_improver_row(
        store,
        when=now - timedelta(hours=1),
        validated=False,
        changed=False,
        rejection="length ratio out of bounds",
    )
    funnel = summarize_improver(store, UsageWindow.last_days(7))
    assert funnel.total_fired == 5
    assert funnel.total_accepted == 2
    assert funnel.total_validated == 4
    assert "length ratio out of bounds" in funnel.top_rejection_reasons


def test_template_effectiveness(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    now = datetime.now(timezone.utc)
    for index in range(3):
        _write_improver_row(
            store,
            when=now - timedelta(hours=index),
            accepted=True,
            templates="good-template",
        )
    _write_improver_row(
        store,
        when=now - timedelta(hours=4),
        accepted=False,
        templates="bad-template",
    )
    rows = template_effectiveness(store, UsageWindow.last_days(7), min_samples=3)
    assert len(rows) == 1
    assert rows[0].template_id == "good-template"
    assert rows[0].accept_rate == 1.0


def test_recall_usage_includes_outcome_fields(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    now = datetime.now(timezone.utc)
    _write_improver_row(store, when=now, templates="a,b")
    rows = store.recall_usage(UsageWindow.last_days(1))
    assert len(rows) == 1
    assert rows[0].improver_context_templates == "a,b"
    assert rows[0].improver_validated is True
    assert rows[0].cursor_mode == "agent"


def test_feedback_store_record_edit(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    feedback = FeedbackStore(connection)
    event = feedback.record_edit(
        original_text="fix tests",
        submitted_text="fix unit tests in src/",
    )
    assert event.edit_distance is not None
    assert event.edit_distance > 0
    assert len(feedback.recent(limit=5)) == 1


def test_optimization_suggestions(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    feedback = FeedbackStore(connection)
    now = datetime.now(timezone.utc)
    for index in range(6):
        _write_improver_row(
            store,
            when=now - timedelta(hours=index),
            accepted=False,
            validated=False,
            changed=False,
            rejection="length ratio out of bounds",
        )
    suggestions = generate_optimization_suggestions(
        store,
        UsageWindow.last_days(7),
        feedback=feedback,
    )
    assert any(item.kind == "improver_tuning" for item in suggestions)
    assert any(item.kind == "validation" for item in suggestions)
