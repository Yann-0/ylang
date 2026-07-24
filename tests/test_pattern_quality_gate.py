"""Tests for learned-template quality gating."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from ylang.core.types import CompletionResult
from ylang.library.pattern_detector import (
    evaluate_learned_template_quality,
    is_trivial_prompt_pattern,
    propose_template_from_pattern_outcome,
)
from ylang.library.patterns import DetectedPattern
from ylang.library.store import open_library, save_learned_template
from ylang.library.types import TemplateParam
from ylang.usage.store import open_store


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("yes", True),
        ("ok", True),
        ("go", True),
        ("what next?", True),
        ("commit and push", True),
        ("fix the login bug in auth.py", False),
    ],
)
def test_is_trivial_prompt_pattern_extended(prompt: str, expected: bool) -> None:
    assert is_trivial_prompt_pattern(prompt) is expected


def test_evaluate_learned_template_quality_rejects_short_body() -> None:
    ok, reason = evaluate_learned_template_quality("Edit {file}")
    assert ok is False
    assert reason is not None
    assert "too short" in reason


def test_evaluate_learned_template_quality_rejects_copy_without_placeholders() -> None:
    sample = "Refactor the gateway routes for async sqlite access"
    ok, reason = evaluate_learned_template_quality(sample, sample_text=sample)
    assert ok is False
    assert reason is not None
    assert "placeholder" in reason.lower()


def test_evaluate_learned_template_quality_accepts_structured_template() -> None:
    body = (
        "Refactor the {module} routes for async sqlite access and add {test_scope} tests."
    )
    sample = "Refactor the gateway routes for async sqlite access"
    params = [
        TemplateParam(name="module", description="Module name", default="gateway"),
        TemplateParam(name="test_scope", description="Test scope", default="unit"),
    ]
    ok, reason = evaluate_learned_template_quality(
        body,
        sample_text=sample,
        params=params,
    )
    assert ok is True
    assert reason is None


def test_propose_template_from_pattern_outcome_rejects_stub_copy() -> None:
    pattern = DetectedPattern(
        pattern_id="gateway-routes",
        sample_text="Refactor the gateway routes for async sqlite access",
        occurrence_count=3,
    )
    outcome = propose_template_from_pattern_outcome(pattern)
    assert outcome.proposal is None
    assert outcome.skip_reason is not None
    assert "wraps the source prompt" in outcome.skip_reason


def test_propose_template_from_pattern_outcome_accepts_synthesized_body() -> None:
    engine = MagicMock()
    engine.complete.return_value = CompletionResult(
        content=(
            '{"body":"Refactor the {module} module with {test_type} tests '
            'covering async sqlite access.","param_names":["module","test_type"]}'
        ),
        model_used="routed/model",
        prompt_tokens=1,
        cost=0.0,
        latency_ms=1,
        success=True,
        error=None,
    )
    pattern = DetectedPattern(
        pattern_id="gateway-routes",
        sample_text="Refactor the gateway routes for async sqlite access",
        occurrence_count=3,
    )
    outcome = propose_template_from_pattern_outcome(pattern, engine=engine)
    assert outcome.proposal is not None
    assert outcome.skip_reason is None
    assert "{module}" in outcome.proposal.body


def test_save_learned_template_rejects_low_quality_body(tmp_path: object) -> None:
    library = open_library(tmp_path / "lib.db")  # type: ignore[operator]
    with pytest.raises(ValueError, match="too short"):
        save_learned_template(
            library,
            "learned-junk",
            name="Junk",
            body="ok",
            params=[],
        )


def test_save_learned_template_accepts_quality_body(tmp_path: object) -> None:
    library = open_library(tmp_path / "lib.db")  # type: ignore[operator]
    body = "Review and refactor {module} with comprehensive {test_scope} coverage."
    template = save_learned_template(
        library,
        "learned-refactor-module",
        name="Refactor module",
        body=body,
        params=[
            TemplateParam(name="module", description="Target module", default="auth"),
            TemplateParam(
                name="test_scope",
                description="Testing scope",
                default="integration",
            ),
        ],
    )
    assert template.source == "learned"


def test_render_patterns_page_shows_skip_reason() -> None:
    from ylang.console.pages import render_patterns_page
    from ylang.library.patterns import DetectedPattern

    html = render_patterns_page(
        [
            DetectedPattern(
                pattern_id="commit-and-push",
                sample_text="commit and push",
                occurrence_count=3,
            )
        ],
        [None],
        skip_reasons=["source prompt is trivial or underspecified"],
    )
    assert "Skipped:" in html
    assert "trivial or underspecified" in html


def test_usage_pattern_detector_skips_commit_and_push_cluster(tmp_path: object) -> None:
    from ylang.library.pattern_detector import UsagePatternDetector

    store = open_store(tmp_path / "commit.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    for sample in ("commit and push", "commit and push!", "commit and push."):
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
