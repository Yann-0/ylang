"""Tests for mode optimizer and semantic pattern detection."""

from __future__ import annotations

from ylang.improver.mode_optimizer import get_mode_config, handle_mode_switch, reset_mode_state
from ylang.library.semantic_pattern_detector import cluster_prompt_texts_semantic


def test_mode_optimizer_limits_differ_by_mode() -> None:
    agent = get_mode_config("agent")
    ask = get_mode_config("ask")
    assert agent.reference_prompt_limit > ask.reference_prompt_limit
    assert agent.learned_template_limit > ask.learned_template_limit


def test_mode_switch_handoff() -> None:
    reset_mode_state()
    first = handle_mode_switch("plan")
    second = handle_mode_switch("debug")
    assert first["previous_mode"] == ""
    assert second["previous_mode"] == "plan"
    assert second["handoff_preserved"] is True
    reset_mode_state()


def test_semantic_clustering_groups_similar_prompts() -> None:
    texts = [
        "fix failing unit tests in ci",
        "repair broken unit tests in pipeline",
        "write documentation for api",
        "document the rest api endpoints",
        "document the rest api endpoints v2",
    ]
    clusters = cluster_prompt_texts_semantic(texts, threshold=0.35)
    assert len(clusters) >= 2
    largest = max(clusters, key=len)
    assert len(largest) >= 2
