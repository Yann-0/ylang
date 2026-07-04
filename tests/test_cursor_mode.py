"""Tests for Cursor mode resolution and mode-aware defaults."""

from __future__ import annotations

from ylang.improver.registry import (
    default_auto_apply,
    mode_guidance,
    resolve_cursor_mode,
)


def test_resolve_mode_from_explicit() -> None:
    resolved = resolve_cursor_mode("edit_file", "implement feature", explicit_mode="plan")
    assert resolved.mode == "plan"
    assert resolved.source == "explicit"


def test_resolve_mode_from_tool_alias() -> None:
    resolved = resolve_cursor_mode("cursor-agent", "do something")
    assert resolved.mode == "agent"
    assert resolved.source == "tool"


def test_resolve_mode_from_mcp_tool_default() -> None:
    resolved = resolve_cursor_mode("edit_file", "change line 1")
    assert resolved.mode == "agent"
    assert resolved.source == "tool"


def test_resolve_mode_from_prompt_debug() -> None:
    resolved = resolve_cursor_mode("generic", "debug this failing test and find root cause")
    assert resolved.mode == "debug"
    assert resolved.source == "prompt"


def test_resolve_mode_from_prompt_ask() -> None:
    resolved = resolve_cursor_mode("generic", "explain how the router works")
    assert resolved.mode == "ask"
    assert resolved.source == "prompt"


def test_resolve_mode_default_agent() -> None:
    resolved = resolve_cursor_mode("unknown-widget", "do the thing")
    assert resolved.mode == "agent"
    assert resolved.source == "default"


def test_default_auto_apply_by_mode() -> None:
    assert default_auto_apply("edit_file", "agent") is False
    assert default_auto_apply("grep", "agent") is True
    assert default_auto_apply("grep", "debug") is False
    assert default_auto_apply("grep", "plan") is False
    assert default_auto_apply("grep", "ask") is True


def test_mode_guidance_covers_all_modes() -> None:
    for mode in ("agent", "plan", "debug", "ask", "multitask"):
        guidance = mode_guidance(mode)
        assert mode in guidance.lower()
