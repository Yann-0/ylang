"""End-to-end improve_prompt tests through the MCP tool layer."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers import call_mcp_tool

pytestmark = pytest.mark.asyncio

_QUICKCARDS_ORIGINAL = (
    "Propose next steps for QuickCards after Wave 18 (migrated ~117 API routes from "
    "supabaseAdmin to @/lib/db-admin). Wave 19 started on @/lib/supabase-new barrel "
    "imports in API routes. 1001 unit tests passing. Deploy via scripts/docker-redeploy-web.sh."
)

_QUICKCARDS_IMPROVED = """## Goal
Propose next steps for QuickCards after Wave 18.

## Current state
- Wave 18: migrated ~117 API routes from supabaseAdmin to @/lib/db-admin
- Wave 19: @/lib/supabase-new barrel imports in API routes (in progress)
- 1001 unit tests passing

## Deliverables
- Ranked Wave 19+ backlog with priorities
- Risks, dependencies, and suggested order of work

## Test plan
- Run 1001 unit tests after each change
- Deploy via scripts/docker-redeploy-web.sh when ready

## Definition of done
- Written roadmap the team can execute without follow-up questions"""


def _mock_completion(improved: str, changes: list[dict[str, str]]) -> MagicMock:
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps({"improved": improved, "changes": changes})
            )
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=100)
    mock_response._hidden_params = {"response_cost": 0.01}
    return mock_response


async def test_improve_prompt_quickcards_restructure_passes_validation(
    mcp_server: Any,
) -> None:
    """Realistic long prompt rewrite must not be silently discarded."""
    changes = [
        {
            "kind": "format",
            "description": "Restructure planning ask into full agent spec",
            "before": _QUICKCARDS_ORIGINAL,
            "after": _QUICKCARDS_IMPROVED,
        }
    ]
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_completion(_QUICKCARDS_IMPROVED, changes),
    ):
        result = await call_mcp_tool(
            mcp_server,
            "improve_prompt",
            {
                "text": _QUICKCARDS_ORIGINAL,
                "tool": "cursor-agent",
                "model": "test-model",
            },
        )

    assert result["original"] == _QUICKCARDS_ORIGINAL
    assert result["improved"] == _QUICKCARDS_IMPROVED
    assert result["improved"] != result["original"]
    assert len(result["changes"]) >= 1
    assert result.get("validated") is True
    assert result.get("rejection_reason") is None
    assert "## Goal" in result["improved"]
    assert "## Definition of done" in result["improved"]


async def test_improve_prompt_salvages_restructured_output(mcp_server: Any) -> None:
    """When change[] validation is brittle, accept a clear markdown spec."""
    original = "Propose next steps. Wave 18 done. 1001 tests passing."
    improved = (
        "## Goal\nPropose next steps.\n\n"
        "## Context\n- Wave 18 done\n- 1001 tests passing\n\n"
        "## Test plan\n- Run 1001 tests first\n\n"
        "## Definition of done\n- Prioritized roadmap"
    )
    changes = [
        {
            "kind": "clarity",
            "description": "bad anchor",
            "before": "nonexistent substring",
            "after": "nope",
        }
    ]
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_completion(improved, changes),
    ):
        result = await call_mcp_tool(
            mcp_server,
            "improve_prompt",
            {"text": original, "tool": "Cursor", "model": "claude-sonnet-4-5"},
        )

    assert result["improved"] == improved
    assert len(result["changes"]) >= 1
    assert result.get("validated") is True
    assert "## Goal" in result["improved"]


async def test_improve_prompt_vague_question_expands(mcp_server: Any) -> None:
    """Short vague prompts should expand, not return empty changes."""
    original = "what shall we do next?"
    improved = (
        "## Goal\nwhat shall we do next?\n\n"
        "## Deliverables\n- Ranked next actions with rationale\n\n"
        "## Definition of done\n- Clear recommendation ready to execute"
    )
    changes = [
        {
            "kind": "scope",
            "description": "Expand vague planning question",
            "before": original,
            "after": improved,
        }
    ]
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_completion(improved, changes),
    ):
        result = await call_mcp_tool(
            mcp_server,
            "improve_prompt",
            {"text": original, "tool": "cursor-agent", "model": "test-model"},
        )

    assert result["improved"] != original
    assert len(result["changes"]) >= 1
    assert result.get("validated") is True
