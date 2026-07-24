"""Tests for improver analytics and optimization modules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ylang.core.db import open_connection
from ylang.core.migrations import run_migrations
from ylang.usage.feedback import FeedbackStore
from ylang.usage.improver_analytics import (
    compute_performance_ratio,
    compute_polish_ratio_from_edits,
    summarize_improver,
    summarize_improver_quality,
    template_effectiveness,
    template_injection_counts,
)
from ylang.usage.optimizer import generate_optimization_suggestions, serialize_funnel
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
    latency_ms: int = 50,
) -> None:
    store.write_usage(
        surface="mcp",
        activity=f"improve:{mode}",
        model_used="test/model",
        prompt_tokens=100,
        cost=0.01,
        improver_fired=True,
        improver_accepted=accepted,
        latency_ms=latency_ms,
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


def test_template_injection_counts(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    now = datetime.now(timezone.utc)
    _write_improver_row(store, when=now, templates="alpha")
    _write_improver_row(store, when=now, templates="alpha,beta")
    counts = template_injection_counts(store, UsageWindow.all_time())
    assert counts["alpha"] == 2
    assert counts["beta"] == 1
    assert counts.get("missing", 0) == 0


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


def test_compute_performance_ratio_targets() -> None:
    assert compute_performance_ratio(1.0, 8000.0) == 1.0
    assert compute_performance_ratio(1.0, 4000.0) == 1.0
    assert compute_performance_ratio(0.5, 16000.0) == 0.25
    assert compute_performance_ratio(0.5, None) is None
    assert compute_performance_ratio(0.5, 0) is None


def test_compute_polish_ratio_from_edits(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    feedback = FeedbackStore(connection)
    # Identical submit → polish 1.0
    feedback.record_edit(original_text="abcdef", submitted_text="abcdef")
    # Distance 3 over len 6 → polish 0.5
    feedback.record_edit(original_text="abcdef", submitted_text="abcXXX")
    polish, count, kept, avg_dist = compute_polish_ratio_from_edits(
        feedback.recall_edits(UsageWindow.last_days(1))
    )
    assert count == 2
    assert polish == 0.75
    assert kept == 0.5
    assert avg_dist is not None and avg_dist > 0


def test_summarize_improver_quality_polish_and_performance(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    feedback = FeedbackStore(connection)
    now = datetime.now(timezone.utc)
    for index in range(4):
        _write_improver_row(
            store,
            when=now - timedelta(hours=index),
            accepted=True,
            latency_ms=4000,
        )
    feedback.record_edit(original_text="hello world", submitted_text="hello world")
    report = summarize_improver_quality(
        store, UsageWindow.last_days(7), feedback
    )
    assert report.quality.performance_ratio == 1.0
    assert report.quality.polish_ratio == 1.0
    assert report.quality.polish_sample_count == 1
    assert report.quality.performance_by_mode["agent"] == 1.0
    payload = serialize_funnel(report.funnel, report.quality)
    assert payload["polish_ratio"] == 1.0
    assert payload["performance_ratio"] == 1.0


def test_summarize_improver_quality_none_without_data(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    feedback = FeedbackStore(connection)
    report = summarize_improver_quality(
        store, UsageWindow.last_days(7), feedback
    )
    assert report.funnel.total_fired == 0
    assert report.quality.performance_ratio is None
    assert report.quality.polish_ratio is None
    assert report.quality.polish_sample_count == 0


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
    validation = next(item for item in suggestions if item.kind == "validation")
    assert validation.priority == "low"
    assert validation.apply_action is None
    applyable = [item for item in suggestions if item.apply_action]
    non_applyable = [item for item in suggestions if not item.apply_action]
    if applyable and non_applyable:
        first_non_idx = next(
            index for index, item in enumerate(suggestions) if not item.apply_action
        )
        last_apply_idx = max(
            index for index, item in enumerate(suggestions) if item.apply_action
        )
        assert last_apply_idx < first_non_idx
    low = next(item for item in suggestions if item.suggestion_id == "improver-accept-rate-low")
    assert low.apply_action == "runtime_setting"
    assert low.setting_key == "learned_template_limit"
    assert low.setting_value == "1"


def test_optimization_suggestions_skips_handled_rejection_reasons(
    db_path: object,
) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    now = datetime.now(timezone.utc)
    for index, reason in enumerate(
        (
            "improver timeout",
            "change.before not anchored to original",
            "improved text changed but changes[] is empty",
        )
    ):
        for offset in range(3):
            _write_improver_row(
                store,
                when=now - timedelta(hours=index * 3 + offset),
                accepted=False,
                validated=False,
                changed=False,
                rejection=reason,
            )
    suggestions = generate_optimization_suggestions(store, UsageWindow.last_days(7))
    validation = [item for item in suggestions if item.kind == "validation"]
    assert validation == []


def test_optimization_suggestions_template_boost_applyable(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    now = datetime.now(timezone.utc)
    for index in range(8):
        _write_improver_row(
            store,
            when=now - timedelta(hours=index),
            accepted=index < 5,
            validated=True,
            changed=True,
            templates="detailed-image-generation-prompt-for-fashion-and-portrait-photography",
        )
    suggestions = generate_optimization_suggestions(store, UsageWindow.last_days(7))
    boost = next(
        item
        for item in suggestions
        if item.suggestion_id.startswith("template-boost-detailed-image")
    )
    assert boost.apply_action == "runtime_setting"
    assert boost.setting_key == "retrieval_preferred_template_ids"
    assert (
        "detailed-image-generation-prompt-for-fashion-and-portrait-photography"
        in (boost.setting_value or "")
    )


def test_optimization_suggestions_timeout_bundle(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    now = datetime.now(timezone.utc)
    for index in range(3):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="test/model",
            prompt_tokens=10,
            cost=0.01,
            improver_fired=True,
            improver_accepted=False,
            improver_validated=False,
            improver_changed=False,
            improver_rejection_reason="improver timeout",
            latency_ms=12000,
            success=False,
            timestamp=now - timedelta(hours=index),
        )
    suggestions = generate_optimization_suggestions(
        store, UsageWindow.last_days(7), runtime_overrides={}
    )
    timeout = next(
        item for item in suggestions if item.suggestion_id == "improver-timeout-raise"
    )
    assert timeout.setting_key == "improver_timeout_sec"
    assert timeout.setting_value == "18"
    fast = next(item for item in suggestions if item.suggestion_id == "improver-fast-models")
    assert fast.setting_key == "models_improve"
    assert "mistral/mistral-small-latest" in fast.setting_value


def test_optimization_suggestions_skips_already_applied_runtime(
    db_path: object,
) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    now = datetime.now(timezone.utc)
    for index in range(6):
        _write_improver_row(
            store,
            when=now - timedelta(hours=index),
            accepted=False,
            validated=False,
            changed=False,
            rejection="improver timeout",
        )
    overrides = {
        "learned_template_limit": "1",
        "improver_timeout_sec": "18",
        "models_improve": "mistral/mistral-small-latest,openai/gpt-4o-mini",
    }
    suggestions = generate_optimization_suggestions(
        store, UsageWindow.last_days(7), runtime_overrides=overrides
    )
    setting_ids = {
        item.suggestion_id
        for item in suggestions
        if item.apply_action == "runtime_setting"
    }
    assert "improver-accept-rate-low" not in setting_ids
    assert "improver-timeout-raise" not in setting_ids
    assert "improver-context-trim" not in setting_ids
    assert "improver-fast-models" not in setting_ids


def test_optimization_suggestions_archive_zero_accept(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS templates (
            template_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            latest_version INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            visibility TEXT NOT NULL DEFAULT 'private',
            tags_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO templates (template_id, name, latest_version, updated_at, visibility)
        VALUES ('junk-zero', 'Junk', 1, ?, 'public')
        """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    connection.commit()
    now = datetime.now(timezone.utc)
    for index in range(5):
        _write_improver_row(
            store,
            when=now - timedelta(hours=index),
            accepted=False,
            validated=False,
            changed=False,
            templates="junk-zero",
        )
    suggestions = generate_optimization_suggestions(store, UsageWindow.last_days(7))
    archive = next(
        item for item in suggestions if item.suggestion_id == "template-archive-junk-zero"
    )
    assert archive.apply_action == "archive_templates"
    assert archive.template_id == "junk-zero"


def test_optimization_suggestions_skips_matching_runtime(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    run_migrations(connection)
    store = UsageStore(connection)
    store._ensure_schema()
    now = datetime.now(timezone.utc)
    for index in range(6):
        _write_improver_row(
            store,
            when=now - timedelta(hours=index),
            accepted=False,
            validated=False,
            changed=False,
            rejection="improver timeout",
        )
    overrides = {
        "learned_template_limit": "1",
        "improver_timeout_sec": "18",
        "models_improve": "mistral/mistral-small-latest,openai/gpt-4o-mini",
    }
    suggestions = generate_optimization_suggestions(
        store,
        UsageWindow.last_days(7),
        runtime_overrides=overrides,
    )
    runtime_ids = {
        item.suggestion_id
        for item in suggestions
        if item.apply_action == "runtime_setting"
    }
    assert "improver-accept-rate-low" not in runtime_ids
    assert "improver-timeout-raise" not in runtime_ids
    assert "improver-context-trim" not in runtime_ids
    assert "improver-fast-models" not in runtime_ids
