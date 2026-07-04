"""Unit tests for prompt-text pattern detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ylang.library.pattern_detector import (
    UsagePatternDetector,
    cluster_prompt_texts,
    normalize_prompt_text,
    pattern_id_from_text,
)
from ylang.usage.store import open_store


def test_normalize_prompt_text_collapses_whitespace() -> None:
    assert normalize_prompt_text("  Fix   the  Bug  ") == "fix the bug"


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


def test_usage_pattern_detector_requires_three_similar_samples(tmp_path: object) -> None:
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
