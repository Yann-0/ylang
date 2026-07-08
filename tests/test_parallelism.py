"""Tests for parallelism detection and multitask/plan mode guidance."""

from __future__ import annotations

from ylang.improver.improver import _build_user_message
from ylang.improver.mode_optimizer import get_mode_config
from ylang.improver.registry import (
    mode_guidance,
    parallelism_directive,
    recommend_parallelism,
    resolve_cursor_mode,
)


def test_recommend_parallelism_explicit_keyword() -> None:
    assert recommend_parallelism("run these in parallel please") is True
    assert recommend_parallelism("use background agents for this") is True


def test_recommend_parallelism_list_items() -> None:
    text = "Do the following:\n- add login\n- add logout\n- add profile page"
    assert recommend_parallelism(text) is True


def test_recommend_parallelism_multiple_verbs() -> None:
    assert recommend_parallelism("implement the API, write tests, and update docs") is True


def test_recommend_parallelism_single_task_false() -> None:
    assert recommend_parallelism("fix the typo in the header") is False


def test_multitask_guidance_mentions_parallel_subagents() -> None:
    guidance = mode_guidance("multitask")
    assert "parallel" in guidance.lower()
    assert "subagent" in guidance.lower()
    assert "integration" in guidance.lower()


def test_plan_guidance_mentions_parallelizable_and_readonly() -> None:
    guidance = mode_guidance("plan")
    assert "read-only" in guidance.lower()
    assert "parallelizable" in guidance.lower()
    assert "roadmap" in guidance.lower()


def test_multitask_config_encourages_parallelism() -> None:
    assert get_mode_config("multitask").encourage_parallelism is True
    assert get_mode_config("plan").encourage_parallelism is True
    assert get_mode_config("ask").encourage_parallelism is False


def test_build_user_message_appends_directive_for_multitask() -> None:
    resolved = resolve_cursor_mode("cursor-multitask", "do stuff", explicit_mode="multitask")
    message = _build_user_message("do stuff", resolved, None)
    assert parallelism_directive() in message


def test_build_user_message_appends_directive_when_detected_in_agent() -> None:
    resolved = resolve_cursor_mode("edit_file", "implement API, write tests, update docs")
    message = _build_user_message(
        "implement API, write tests, update docs",
        resolved,
        None,
    )
    assert "Parallelization directive" in message


def test_build_user_message_no_directive_for_simple_agent_prompt() -> None:
    resolved = resolve_cursor_mode("edit_file", "fix the header typo", explicit_mode="agent")
    message = _build_user_message("fix the header typo", resolved, None)
    assert "Parallelization directive" not in message
