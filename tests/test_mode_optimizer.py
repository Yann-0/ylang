"""Tests for mode optimizer and semantic pattern detection."""

from __future__ import annotations

from ylang.improver.mode_optimizer import (
    apply_fast_path_config,
    get_mode_config,
    handle_mode_switch,
    improver_timeout_sec,
    reset_mode_state,
)
from ylang.library.semantic_pattern_detector import cluster_prompt_texts_semantic


def test_mode_optimizer_limits_differ_by_mode() -> None:
    agent = get_mode_config("agent")
    ask = get_mode_config("ask")
    assert agent.reference_prompt_limit > ask.reference_prompt_limit
    assert agent.learned_template_limit > ask.learned_template_limit


def test_apply_fast_path_config_tightens_limits() -> None:
    agent = get_mode_config("agent")
    fast = apply_fast_path_config(agent, timeout_sec=18.0)
    assert fast.conversation_turn_limit <= agent.conversation_turn_limit
    assert fast.reference_prompt_char_limit < agent.reference_prompt_char_limit
    assert fast.learned_template_limit <= agent.learned_template_limit
    ultra = apply_fast_path_config(agent, timeout_sec=12.0)
    assert ultra.learned_template_limit == 0
    assert ultra.reference_prompt_limit == 1
    assert ultra.conversation_char_limit <= fast.conversation_char_limit
    unchanged = apply_fast_path_config(agent, timeout_sec=25.0)
    assert unchanged == agent


def test_improver_timeout_sec_reads_runtime_override(tmp_path: object) -> None:
    from ylang.core.runtime_settings import RuntimeSettingsStore
    from ylang.usage.store import open_store

    store = open_store(tmp_path / "timeout.db")  # type: ignore[operator]
    RuntimeSettingsStore(store._connection).set("improver_timeout_sec", "18")
    assert improver_timeout_sec(store) == 18.0


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
