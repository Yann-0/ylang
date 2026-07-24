"""Unit tests for prompt-text pattern detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from ylang.core.types import CompletionResult
from ylang.library.pattern_detector import (
    UsagePatternDetector,
    cluster_prompt_texts,
    is_trivial_prompt_pattern,
    normalize_prompt_text,
    pattern_id_from_text,
    synthesize_template_from_pattern,
)
from ylang.library.patterns import DetectedPattern
from ylang.usage.store import open_store


def test_normalize_prompt_text_collapses_whitespace() -> None:
    assert normalize_prompt_text("  Fix   the  Bug  ") == "fix the bug"


def test_is_trivial_prompt_pattern() -> None:
    assert is_trivial_prompt_pattern("ok")
    assert is_trivial_prompt_pattern("continue")
    assert is_trivial_prompt_pattern("what next?")
    assert is_trivial_prompt_pattern("commit and push")
    assert not is_trivial_prompt_pattern("fix the login bug in auth.py")


def test_usage_pattern_detector_skips_trivial_prompts(tmp_path: object) -> None:
    store = open_store(tmp_path / "trivial.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    for sample in ("ok", "ok!", "ok."):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="m",
            prompt_tokens=1,
            cost=0.0,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=1,
            success=True,
            timestamp=now - timedelta(days=1),
            improver_input_sample=sample,
        )
    detector = UsagePatternDetector(store)
    assert detector.detect(window_days=30) == []


def test_cluster_prompt_texts_groups_similar_prompts() -> None:
    texts = [
        "Fix the login bug in auth.py",
        "fix the login bug in auth.py please",
        "Fix the login bug in auth.py!",
        "Write unit tests for parser",
    ]
    clusters = cluster_prompt_texts(texts)
    assert len(clusters) == 2
    login_cluster = max(clusters, key=len)
    assert len(login_cluster) == 3


def test_usage_pattern_detector_requires_three_similar_samples(
    tmp_path: object,
) -> None:
    store = open_store(tmp_path / "patterns.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    prompt = "Refactor the gateway routes for async sqlite"
    for _ in range(3):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="m",
            prompt_tokens=1,
            cost=0.0,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=1,
            success=True,
            timestamp=now - timedelta(days=1),
            improver_input_sample=prompt,
        )
    detector = UsagePatternDetector(store)
    patterns = detector.detect(window_days=30)
    assert len(patterns) == 1
    assert patterns[0].occurrence_count == 3
    assert "gateway routes" in patterns[0].sample_text.lower()


def test_usage_pattern_detector_ignores_rows_without_sample(tmp_path: object) -> None:
    store = open_store(tmp_path / "empty.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    for _ in range(5):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="m",
            prompt_tokens=1,
            cost=0.0,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=1,
            success=True,
            timestamp=now - timedelta(days=1),
        )
    detector = UsagePatternDetector(store)
    assert detector.detect(window_days=30) == []


def test_pattern_id_from_text_is_stable() -> None:
    first = pattern_id_from_text("Add tests for budget meter edge cases")
    second = pattern_id_from_text("Add tests for budget meter edge cases")
    assert first == second


def test_synthesize_template_defaults_to_router_model() -> None:
    """Synthesis must not hardcode a Claude slug; omit model for activity routing."""
    engine = MagicMock()
    engine.complete.return_value = CompletionResult(
        content='{"body":"Do {task}","param_names":["task"]}',
        model_used="routed/model",
        prompt_tokens=1,
        cost=0.0,
        latency_ms=1,
        success=True,
        error=None,
    )
    pattern = DetectedPattern(
        pattern_id="fix-login",
        sample_text="Fix the login bug",
        occurrence_count=3,
    )
    body = synthesize_template_from_pattern(pattern, engine)
    assert body == "Do {task}"
    call_kwargs = engine.complete.call_args.kwargs
    assert call_kwargs.get("model") is None
    assert call_kwargs.get("activity") == "improve:agent"
    assert "claude-sonnet" not in str(engine.complete.call_args)


def test_pattern_detector_hot_reload_from_runtime_settings(tmp_path: object) -> None:
    from ylang.core.runtime_settings import RuntimeSettingsStore
    from ylang.library import patterns
    from ylang.library.semantic_pattern_detector import SemanticPatternDetector
    from ylang.usage.store import open_store

    store = open_store(tmp_path / "hot-reload.db")  # type: ignore[operator]
    runtime = RuntimeSettingsStore(store._connection)
    runtime.set("pattern_detector", "semantic")

    patterns.register_pattern_detector_store(store)
    patterns.ensure_pattern_detector()

    assert patterns._REGISTERED_MODE == "semantic"
    assert isinstance(patterns._PATTERN_DETECTOR, SemanticPatternDetector)

