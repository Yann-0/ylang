"""Tests for usage activity normalization."""

from __future__ import annotations

from ylang.usage.activity import normalize_usage_activity


def test_normalize_improve_cursor_variants_to_agent() -> None:
    assert normalize_usage_activity("improve:cursor") == "improve:agent"
    assert normalize_usage_activity("improve:Cursor") == "improve:agent"
    assert normalize_usage_activity("improve:cursor-agent") == "improve:agent"


def test_normalize_improve_canonical_modes_unchanged() -> None:
    assert normalize_usage_activity("improve:agent") == "improve:agent"
    assert normalize_usage_activity("improve:plan") == "improve:plan"
    assert normalize_usage_activity("improve:multitask") == "improve:multitask"


def test_normalize_improve_unknown_suffix_lowercased() -> None:
    assert normalize_usage_activity("improve:edit_file") == "improve:edit_file"


def test_normalize_gateway_activities_lowercased() -> None:
    assert normalize_usage_activity("code") == "code"
    assert normalize_usage_activity("CODE") == "code"
