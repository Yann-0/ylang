"""Tests for improver context building and message formatting."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ylang.core import Engine
from ylang.core.stores import open_stores
from ylang.improver.context import ImproveContext, build_improve_context, _EMPTY_CONVERSATION
from ylang.improver.improver import Improver, _build_user_message
from ylang.improver.registry import resolve_cursor_mode


@pytest.fixture
def backends(tmp_path: Path):
    stores = open_stores(tmp_path / "ylang.db")
    yield stores
    stores.close()


def test_build_improve_context_empty_conversation_includes_facts_and_reference(backends) -> None:
    """Empty or missing conversation still yields facts and reference prompts."""
    backends.memory.remember("project uses pytest", "private")

    context = build_improve_context(
        "summarize this code",
        "code-explain",
        None,
        backends.library,
        backends.memory,
    )
    assert context.conversation_block == _EMPTY_CONVERSATION
    assert context.facts_block is not None
    assert "pytest" in context.facts_block
    assert context.reference_prompts_block is not None
    assert context.has_content is True


def test_build_improve_context_caps(backends) -> None:
    conversation = [
        {"role": "user", "content": f"turn {index}"} for index in range(30)
    ]
    for index in range(25):
        backends.memory.remember(f"fact number {index}", "private")

    context = build_improve_context(
        "summarize this code",
        "code-explain",
        conversation,
        backends.library,
        backends.memory,
    )
    assert context.conversation_block is not None
    assert context.conversation_block.count("turn") <= 20
    assert context.facts_block is not None
    assert context.facts_block.count("- ") <= 20
    assert context.reference_prompts_block is not None
    assert "code-explain" in context.reference_prompts_block.lower()


def test_build_improve_context_includes_learned_templates(backends) -> None:
    from ylang.library.store import save_learned_template
    from ylang.library.types import TemplateParam

    save_learned_template(
        backends.library,
        "learned-test-pattern",
        name="Test Pattern",
        body="Always include edge cases for {topic}.",
        params=[TemplateParam(name="topic", description="Topic", default="tests")],
    )
    context = build_improve_context(
        "add tests",
        "edit_file",
        None,
        backends.library,
        backends.memory,
    )
    assert context.reference_prompts_block is not None
    assert "learned-test-pattern" in context.reference_prompts_block


def test_build_user_message_always_includes_all_context_sections() -> None:
    """When context is provided, all three sections appear even if blocks are empty."""
    context = ImproveContext()
    resolved = resolve_cursor_mode("edit_file", "fix bug")
    message = _build_user_message("fix bug", resolved, context)
    assert "Cursor mode: agent" in message
    assert "Recent conversation:" in message
    assert "(No prior conversation provided.)" in message
    assert "Project facts:" in message
    assert "(No project facts stored.)" in message
    assert "Reference prompts:" in message
    assert "(No matching reference prompts found.)" in message
    assert "Text:\nfix bug" in message


def test_build_user_message_includes_context_blocks() -> None:
    context = ImproveContext(
        conversation_block="user: hello",
        facts_block="- uses pytest (private)",
        reference_prompts_block="### Summarize (summarize)\ntags: summarize\nbody",
    )
    message = _build_user_message(
        "fix bug",
        resolve_cursor_mode("edit_file", "fix bug"),
        context,
    )
    assert "Recent conversation:" in message
    assert "Project facts:" in message
    assert "Reference prompts:" in message
    assert "Text:\nfix bug" in message


def test_improver_passes_context_to_engine(backends) -> None:
    engine = Engine(backends.store, surface="test")
    improver = Improver(engine)
    context = ImproveContext(conversation_block="user: prior ask")

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"improved": "fix the bug", "changes": []}',
            )
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response) as mocked:
        improver.improve("fix teh bug", "edit_file", model="test-model", context=context)

    messages = mocked.call_args.kwargs["messages"]
    user_message = messages[1]["content"]
    assert "Recent conversation:" in user_message
    assert "prior ask" in user_message


def test_build_user_message_without_context_unchanged() -> None:
    resolved = resolve_cursor_mode("edit_file", "fix bug")
    message = _build_user_message("fix bug", resolved, None)
    assert "Tool context: edit_file" in message
    assert "Cursor mode: agent" in message
    assert "Text:\nfix bug" in message
