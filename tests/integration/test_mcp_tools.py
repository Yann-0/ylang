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
    assert result["cursor_mode"] == "agent"
    assert result["mode_source"] == "tool"

    usage = await call_mcp_tool(mcp_server, "recall_usage", {"last_hours": 1})
    assert usage["ok"] is True
    assert len(usage["rows"]) == 1
    assert usage["rows"][0]["activity"] == "improve:agent"
    assert usage["rows"][0]["improver_fired"] is True
    assert usage["rows"][0]["improver_accepted"] is True
    assert usage["rows"][0]["success"] is True
    assert usage["rows"][0]["prompt_tokens"] == 42


async def test_improve_prompt_record_acceptance_only(mcp_server: Any) -> None:
    """record_acceptance_only patches the latest usage row without calling the LLM."""
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({"improved": "hello", "changes": []})))
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        await call_mcp_tool(
            mcp_server,
            "improve_prompt",
            {"text": "hello", "tool": "edit_file", "model": "test-model"},
        )

    usage_before = await call_mcp_tool(mcp_server, "recall_usage", {"last_hours": 1})
    assert usage_before["rows"][0]["improver_accepted"] is False

    recorded = await call_mcp_tool(
        mcp_server,
        "improve_prompt",
        {
            "text": "ignored",
            "tool": "edit_file",
            "model": "test-model",
            "accepted": True,
            "record_acceptance_only": True,
        },
    )
    assert recorded["ok"] is True
    assert recorded["recorded"] is True

    usage_after = await call_mcp_tool(mcp_server, "recall_usage", {"last_hours": 1})
    assert len(usage_after["rows"]) == 1
    assert usage_after["rows"][0]["improver_accepted"] is True


async def test_improve_prompt_explicit_mode(mcp_server: Any) -> None:
    """improve_prompt honors explicit mode override."""
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"improved": "explain the router", "changes": []}',
            )
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = await call_mcp_tool(
            mcp_server,
            "improve_prompt",
            {
                "text": "explain the router",
                "tool": "grep",
                "model": "test-model",
                "mode": "ask",
                "use_context": False,
            },
        )

    assert result["cursor_mode"] == "ask"
    assert result["mode_source"] == "explicit"
    assert result["auto_apply_default"] is True


async def test_save_template_visibility(mcp_server: Any) -> None:
    """save_template persists visibility and tags."""
    result = await call_mcp_tool(
        mcp_server,
        "save_template",
        {
            "template_id": "public-prompt",
            "name": "Public Prompt",
            "body": "Do {task}",
            "params": [{"name": "task", "description": "Task", "default": None}],
            "visibility": "public",
            "tags": ["edit_file", "refactor"],
        },
    )
    assert result["ok"] is True
    assert result["visibility"] == "public"
    assert result["tags"] == ["edit_file", "refactor"]


async def test_list_templates_visibility_filter(mcp_server: Any) -> None:
    """list_templates filters by visibility when requested."""
    await call_mcp_tool(
        mcp_server,
        "save_template",
        {
            "template_id": "private-only",
            "name": "Private",
            "body": "secret",
            "params": [],
            "visibility": "private",
        },
    )
    public_rows = await call_mcp_tool(
        mcp_server,
        "list_templates",
        {"visibility": "public"},
    )
    public_ids = {item["template_id"] for item in public_rows["templates"]}
    assert "private-only" not in public_ids
    assert "summarize" in public_ids


async def test_improve_prompt_use_context_enriches_message(mcp_server: Any) -> None:
    """improve_prompt with use_context passes conversation and facts to the model."""
    await call_mcp_tool(
        mcp_server,
        "remember",
        {"fact": "project uses pytest", "scope": "private"},
    )
    original = "summarize the code"
    improved = "## Goal\nSummarize the code clearly."
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "improved": improved,
                        "changes": [
                            {
                                "kind": "format",
                                "description": "Add goal section",
                                "before": original,
                                "after": improved,
                            }
                        ],
                    }
                )
            )
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=50)
    mock_response._hidden_params = {"response_cost": 0.001}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response) as mocked:
        result = await call_mcp_tool(
            mcp_server,
            "improve_prompt",
            {
                "text": original,
                "tool": "code-explain",
                "model": "test-model",
                "use_context": True,
                "conversation": [{"role": "user", "content": "explain this function"}],
            },
        )

    user_message = mocked.call_args.kwargs["messages"][1]["content"]
    assert "Recent conversation:" in user_message
    assert "explain this function" in user_message
    assert "Project facts:" in user_message
    assert "pytest" in user_message
    assert "Reference prompts:" in user_message
    assert result["improved"] == improved
    assert result["context_used"]["had_conversation_input"] is True
    assert result["context_used"]["facts_count"] >= 1


async def test_improve_prompt_default_includes_context(mcp_server: Any) -> None:
    """improve_prompt without use_context arg includes facts and reference prompts."""
    await call_mcp_tool(
        mcp_server,
        "remember",
        {"fact": "project uses pytest", "scope": "private"},
    )
    original = "summarize the code"
    improved = "## Goal\nSummarize the code clearly."
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "improved": improved,
                        "changes": [],
                    }
                )
            )
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=50)
    mock_response._hidden_params = {"response_cost": 0.001}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response) as mocked:
        result = await call_mcp_tool(
            mcp_server,
            "improve_prompt",
            {
                "text": original,
                "tool": "code-explain",
                "model": "test-model",
            },
        )

    user_message = mocked.call_args.kwargs["messages"][1]["content"]
    assert "Recent conversation:" in user_message
    assert "(No prior conversation provided.)" in user_message
    assert "Project facts:" in user_message
    assert "pytest" in user_message
    assert "Reference prompts:" in user_message
    assert result["context_used"]["had_conversation_input"] is False
    assert result["context_used"]["facts_count"] >= 1


async def test_improve_prompt_use_context_false_disables_context(mcp_server: Any) -> None:
    """improve_prompt with use_context=false omits context blocks and metadata."""
    await call_mcp_tool(
        mcp_server,
        "remember",
        {"fact": "project uses pytest", "scope": "private"},
    )
    original = "fix teh bug"
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps({"improved": original, "changes": []}),
            )
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response) as mocked:
        result = await call_mcp_tool(
            mcp_server,
            "improve_prompt",
            {
                "text": original,
                "tool": "edit_file",
                "model": "test-model",
                "use_context": False,
            },
        )

    user_message = mocked.call_args.kwargs["messages"][1]["content"]
    assert "Project facts:" not in user_message
    assert "Reference prompts:" not in user_message
    assert "Recent conversation:" not in user_message
    assert "context_used" not in result


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

    assert result["ok"] is True
    assert result["template_id"] == "my-prompt"
    assert result["name"] == "My Prompt"
    assert result["version"] == 1
    assert result["source"] == "user"
    assert result["body"] == "Do {task} in {style}."
    assert [p["name"] for p in result["params"]] == ["task", "style"]


async def test_save_template_version_two(mcp_server: Any) -> None:
    """save_template increments version for the same template_id."""
    payload = {
        "template_id": "versioned",
        "name": "V1",
        "body": "version one",
        "params": [],
    }
    await call_mcp_tool(mcp_server, "save_template", payload)
    payload["name"] = "V2"
    payload["body"] = "version two"
    result = await call_mcp_tool(mcp_server, "save_template", payload)
    assert result["version"] == 2
    recall = await call_mcp_tool(
        mcp_server,
        "recall_template",
        {"template_id": "versioned", "version": 1},
    )
    assert recall["body"] == "version one"
    latest = await call_mcp_tool(mcp_server, "recall_template", {"template_id": "versioned"})
    assert latest["body"] == "version two"


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


async def test_recall_template_missing_param(mcp_server: Any) -> None:
    """recall_template returns structured error when a required param is missing."""
    result = await call_mcp_tool(
        mcp_server,
        "recall_template",
        {
            "template_id": "code-explain",
            "param_values": {"language": "Rust"},
        },
    )
    assert result["found"] is True
    assert result["ok"] is False
    assert "missing required param" in result["error"]


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
    assert result["ok"] is True
    ids = {item["template_id"] for item in result["templates"]}
    assert ids == {"summarize", "code-explain", "structured-output"}
    assert all(item["source"] == "seed" for item in result["templates"])


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
    assert len(user_rows["templates"]) == 1
    assert user_rows["templates"][0]["template_id"] == "user-only"

    seed_rows = await call_mcp_tool(
        mcp_server,
        "list_templates",
        {"source": "seed"},
    )
    assert len(seed_rows["templates"]) == 3


async def test_import_public_prompts_from_fixture(mcp_server: Any) -> None:
    """import_public_prompts loads CSV rows into the connected library."""
    from pathlib import Path
    from unittest.mock import patch

    fixture = Path(__file__).parent.parent / "fixtures" / "sample_prompts.csv"
    with patch(
        "ylang.importer.load_csv_text",
        return_value=fixture.read_text(encoding="utf-8"),
    ):
        result = await call_mcp_tool(
            mcp_server,
            "import_public_prompts",
            {"url": "https://example.test/prompts.csv"},
        )

    assert result["ok"] is True
    assert result["imported"] == 3
    assert result["skipped"] == 0

    listed = await call_mcp_tool(mcp_server, "list_templates", {"source": "seed"})
    ids = {item["template_id"] for item in listed["templates"]}
    assert "character" in ids
    assert "job-interviewer" in ids


async def test_list_templates_invalid_source(mcp_server: Any) -> None:
    """list_templates returns structured error for invalid source."""
    result = await call_mcp_tool(mcp_server, "list_templates", {"source": "invalid"})
    assert result["ok"] is False
    assert result["templates"] == []


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


async def test_recall_facts_returns_remembered(mcp_server: Any) -> None:
    """recall_facts returns facts persisted via remember."""
    await call_mcp_tool(
        mcp_server,
        "remember",
        {"fact": "uses vim", "scope": "shareable"},
    )
    result = await call_mcp_tool(mcp_server, "recall_facts", {"scope": "shareable"})
    assert result["ok"] is True
    assert len(result["facts"]) == 1
    assert result["facts"][0]["fact"] == "uses vim"


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
    activities = {row["activity"] for row in rows["rows"]}
    assert rows["ok"] is True
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
    assert rows["ok"] is True
    assert len(rows["rows"]) == 1
    assert rows["rows"][0]["activity"] == "test:week"


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
    assert rows["ok"] is True
    assert len(rows["rows"]) == 1
    assert rows["rows"][0]["activity"] == "test:in"


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
    assert rows["ok"] is True
    assert len(rows["rows"]) == 1
    assert rows["rows"][0]["activity"] == "test:default"


async def test_usage_summary(mcp_server: Any, ylang_deps: Any) -> None:
    """usage_summary aggregates rows in the requested window."""
    now = datetime.now(timezone.utc)
    ylang_deps.store.write_usage(
        surface="mcp",
        activity="code",
        model_used="openai/gpt-4o",
        prompt_tokens=100,
        cost=0.05,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=10,
        success=True,
        timestamp=now - timedelta(hours=1),
    )
    result = await call_mcp_tool(mcp_server, "usage_summary", {"last_hours": 24})
    assert result["ok"] is True
    assert result["total_requests"] == 1
    assert result["total_cost"] == 0.05
    assert result["by_activity"]["code"] == 1


async def test_save_learned_template(mcp_server: Any) -> None:
    """save_learned_template persists a learned-source template."""
    result = await call_mcp_tool(
        mcp_server,
        "save_learned_template",
        {
            "template_id": "learned-edit-file",
            "name": "Learned Edit",
            "body": "Edit {file}",
            "params": [{"name": "file", "description": "Path", "default": None}],
        },
    )
    assert result["ok"] is True
    assert result["source"] == "learned"


async def test_detect_patterns_with_usage(mcp_server: Any, ylang_deps: Any) -> None:
    """detect_patterns finds repeated similar improver prompt texts."""
    now = datetime.now(timezone.utc)
    prompt = "Refactor the authentication module with tests"
    for index in range(3):
        ylang_deps.store.write_usage(
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
            improver_input_sample=prompt if index == 0 else f"{prompt} please",
        )
    result = await call_mcp_tool(mcp_server, "detect_patterns", {"window_days": 30})
    assert result["ok"] is True
    assert len(result["patterns"]) >= 1
    assert len(result["proposals"]) >= 1


async def test_all_tools_registered(mcp_server: Any) -> None:
    """MCP server exposes all Ylang tools."""
    tools = await mcp_server.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "improve_prompt",
        "save_template",
        "recall_template",
        "list_templates",
        "import_public_prompts",
        "remember",
        "recall_facts",
        "recall_usage",
        "usage_summary",
        "detect_patterns",
        "save_learned_template",
        "search_templates",
    }
