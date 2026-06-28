"""Integration tests for Ylang MCP tools against wired backends."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers import call_mcp_tool

pytestmark = pytest.mark.asyncio


async def test_improve_prompt_mocked_litellm(mcp_server: Any) -> None:
    """improve_prompt returns serialized ImprovementResult and logs usage."""
    original = "fix teh bug in main.py"
    improved = "fix the bug in main.py"
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "improved": improved,
                        "changes": [
                            {
                                "kind": "clarity",
                                "description": "Fix spelling",
                                "before": "teh",
                                "after": "the",
                            }
                        ],
                    }
                )
            )
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=42)
    mock_response._hidden_params = {"response_cost": 0.001}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = await call_mcp_tool(
            mcp_server,
            "improve_prompt",
            {"text": original, "tool": "edit_file", "model": "test-model"},
        )

    assert result["original"] == original
    assert result["improved"] == improved
    assert len(result["changes"]) == 1
    assert result["changes"][0]["kind"] == "clarity"
    assert result["auto_apply_default"] is False

    usage = await call_mcp_tool(mcp_server, "recall_usage", {"last_hours": 1})
    assert len(usage) == 1
    assert usage[0]["activity"] == "improve:edit_file"
    assert usage[0]["improver_fired"] is True
    assert usage[0]["success"] is True
    assert usage[0]["prompt_tokens"] == 42


async def test_save_template(mcp_server: Any) -> None:
    """save_template persists a user template version."""
    result = await call_mcp_tool(
        mcp_server,
        "save_template",
        {
            "template_id": "my-prompt",
            "name": "My Prompt",
            "body": "Do {task} in {style}.",
            "params": [
                {"name": "task", "description": "What to do", "default": None},
                {"name": "style", "description": "How", "default": "brief"},
            ],
        },
    )

    assert result["template_id"] == "my-prompt"
    assert result["name"] == "My Prompt"
    assert result["version"] == 1
    assert result["source"] == "user"
    assert result["body"] == "Do {task} in {style}."
    assert [p["name"] for p in result["params"]] == ["task", "style"]


async def test_recall_template_found_without_render(mcp_server: Any) -> None:
    """recall_template returns seed template metadata when found."""
    result = await call_mcp_tool(
        mcp_server,
        "recall_template",
        {"template_id": "summarize"},
    )

    assert result["found"] is True
    assert result["template_id"] == "summarize"
    assert result["version"] == 1
    assert "{text}" in result["body"]
    assert "rendered" not in result


async def test_recall_template_with_render(mcp_server: Any) -> None:
    """recall_template renders body when param_values supplied."""
    result = await call_mcp_tool(
        mcp_server,
        "recall_template",
        {
            "template_id": "summarize",
            "param_values": {"text": "Hello world", "length": "50"},
        },
    )

    assert result["found"] is True
    assert result["rendered"] == "Summarize the following text in about 50 words.\n\nHello world"


async def test_recall_template_not_found(mcp_server: Any) -> None:
    """recall_template returns found=False for unknown ids."""
    result = await call_mcp_tool(
        mcp_server,
        "recall_template",
        {"template_id": "does-not-exist"},
    )
    assert result == {"found": False}


async def test_list_templates_all(mcp_server: Any) -> None:
    """list_templates returns seed templates by default."""
    result = await call_mcp_tool(mcp_server, "list_templates", {})

    ids = {item["template_id"] for item in result}
    assert ids == {"summarize", "code-explain", "structured-output"}
    assert all(item["source"] == "seed" for item in result)


async def test_list_templates_source_filter(mcp_server: Any) -> None:
    """list_templates filters by source when requested."""
    await call_mcp_tool(
        mcp_server,
        "save_template",
        {
            "template_id": "user-only",
            "name": "User Only",
            "body": "plain text",
            "params": [],
        },
    )

    user_rows = await call_mcp_tool(
        mcp_server,
        "list_templates",
        {"source": "user"},
    )
    assert len(user_rows) == 1
    assert user_rows[0]["template_id"] == "user-only"

    seed_rows = await call_mcp_tool(
        mcp_server,
        "list_templates",
        {"source": "seed"},
    )
    assert len(seed_rows) == 3


async def test_remember_persists_fact(mcp_server: Any) -> None:
    """remember persists a fact under private scope."""
    result = await call_mcp_tool(
        mcp_server,
        "remember",
        {"fact": "prefers dark mode", "scope": "private"},
    )

    assert result["ok"] is True
    assert result["id"] == 1
    assert result["fact"] == "prefers dark mode"
    assert result["scope"] == "private"
    assert "created_at" in result


async def test_remember_invalid_scope(mcp_server: Any) -> None:
    """remember returns ok=False for invalid scope values."""
    result = await call_mcp_tool(
        mcp_server,
        "remember",
        {"fact": "prefers dark mode", "scope": "ui"},
    )

    assert result["ok"] is False
    assert "scope must be private or shareable" in result["error"]


async def test_recall_usage_last_hours(mcp_server: Any, ylang_deps: Any) -> None:
    """recall_usage last_hours returns rows inside the window."""
    now = datetime.now(timezone.utc)
    store = ylang_deps.store
    store.write_usage(
        surface="mcp",
        activity="test:recent",
        model_used="m",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now - timedelta(minutes=30),
    )
    store.write_usage(
        surface="mcp",
        activity="test:old",
        model_used="m",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now - timedelta(hours=5),
    )

    rows = await call_mcp_tool(mcp_server, "recall_usage", {"last_hours": 2})
    activities = {row["activity"] for row in rows}
    assert activities == {"test:recent"}


async def test_recall_usage_last_days(mcp_server: Any, ylang_deps: Any) -> None:
    """recall_usage last_days returns rows inside the window."""
    now = datetime.now(timezone.utc)
    ylang_deps.store.write_usage(
        surface="mcp",
        activity="test:week",
        model_used="m",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now - timedelta(days=2),
    )

    rows = await call_mcp_tool(mcp_server, "recall_usage", {"last_days": 7})
    assert len(rows) == 1
    assert rows[0]["activity"] == "test:week"


async def test_recall_usage_since_until(mcp_server: Any, ylang_deps: Any) -> None:
    """recall_usage since/until returns rows in the half-open interval."""
    since = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    until = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    store = ylang_deps.store
    store.write_usage(
        surface="mcp",
        activity="test:in",
        model_used="m",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=since + timedelta(hours=1),
    )
    store.write_usage(
        surface="mcp",
        activity="test:out",
        model_used="m",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=until,
    )

    rows = await call_mcp_tool(
        mcp_server,
        "recall_usage",
        {
            "since": since.isoformat(),
            "until": until.isoformat(),
        },
    )
    assert len(rows) == 1
    assert rows[0]["activity"] == "test:in"


async def test_recall_usage_default_window(mcp_server: Any, ylang_deps: Any) -> None:
    """recall_usage with no window args defaults to last 7 days."""
    now = datetime.now(timezone.utc)
    ylang_deps.store.write_usage(
        surface="mcp",
        activity="test:default",
        model_used="m",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now - timedelta(days=3),
    )

    rows = await call_mcp_tool(mcp_server, "recall_usage", {})
    assert len(rows) == 1
    assert rows[0]["activity"] == "test:default"


async def test_all_six_tools_registered(mcp_server: Any) -> None:
    """MCP server exposes exactly the six Phase 1 tools."""
    tools = await mcp_server.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "improve_prompt",
        "save_template",
        "recall_template",
        "list_templates",
        "remember",
        "recall_usage",
    }
