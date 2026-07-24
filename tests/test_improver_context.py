"""Tests for improver context building and message formatting."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ylang.core import Engine
from ylang.core.stores import open_stores
from ylang.improver.context import (
    ImproveContext,
    build_improve_context,
    _EMPTY_CONVERSATION,
)
from ylang.improver.improver import Improver, _build_user_message
from ylang.improver.registry import resolve_cursor_mode


@pytest.fixture
def backends(tmp_path: Path):
    stores = open_stores(tmp_path / "ylang.db")
    yield stores
    stores.close()


def test_build_improve_context_empty_conversation_includes_facts_and_reference(
    backends,
) -> None:
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


def test_build_improve_context_caps(backends, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "25")
    conversation = [{"role": "user", "content": f"turn {index}"} for index in range(30)]
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


def test_build_improve_context_fast_path_caps(backends, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "18")
    conversation = [{"role": "user", "content": f"turn {index}"} for index in range(30)]

    context = build_improve_context(
        "summarize this code",
        "code-explain",
        conversation,
        backends.library,
        backends.memory,
        store=backends.store,
    )
    assert context.conversation_block is not None
    assert context.conversation_block.count("turn") <= 10


def test_build_improve_context_includes_learned_templates(
    backends, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ylang.library.store import save_learned_template
    from ylang.library.types import TemplateParam

    # Above fast-path threshold so learned_template_limit stays enabled.
    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "25")
    save_learned_template(
        backends.library,
        "learned-test-pattern",
        name="Test Pattern",
        body="Always include edge cases and regression tests for {topic}.",
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


def test_learned_template_limit_from_runtime_settings(
    backends, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ylang.core.runtime_settings import RuntimeSettingsStore
    from ylang.library.store import save_learned_template
    from ylang.library.types import TemplateParam

    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "25")
    for index in range(3):
        save_learned_template(
            backends.library,
            f"learned-limit-{index}",
            name=f"Pattern {index}",
            body=(
                f"Include edge cases and regression tests for pattern {index} "
                "using {topic}."
            ),
            params=[TemplateParam(name="topic", description="Topic", default="tests")],
        )

    RuntimeSettingsStore(backends.store._connection).set("learned_template_limit", "1")
    context = build_improve_context(
        "add tests",
        "edit_file",
        None,
        backends.library,
        backends.memory,
        store=backends.store,
    )
    assert context.reference_prompts_block is not None
    learned_ids = [
        template_id
        for template_id in context.reference_template_ids
        if template_id.startswith("learned-limit-")
    ]
    assert len(learned_ids) == 1


def test_zero_accept_learned_templates_excluded_from_context(
    backends, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    from ylang.library.store import save_learned_template
    from ylang.library.types import TemplateParam

    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "25")
    save_learned_template(
        backends.library,
        "learned-good",
        name="Good Pattern",
        body="Provide helpful guidance for improving {topic} with concrete examples.",
        params=[TemplateParam(name="topic", description="Topic", default="tests")],
    )
    save_learned_template(
        backends.library,
        "learned-bad",
        name="Bad Pattern",
        body="Provide noisy guidance for improving {topic} without useful detail.",
        params=[TemplateParam(name="topic", description="Topic", default="tests")],
    )
    now = datetime.now(timezone.utc)
    for _ in range(43):
        backends.store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="test/model",
            prompt_tokens=10,
            cost=0.01,
            improver_fired=True,
            improver_accepted=False,
            improver_validated=True,
            improver_changed=True,
            improver_context_templates="learned-bad",
            latency_ms=50,
            success=True,
            timestamp=now,
        )

    context = build_improve_context(
        "add tests",
        "edit_file",
        None,
        backends.library,
        backends.memory,
        store=backends.store,
    )
    assert context.reference_prompts_block is not None
    assert "learned-good" in context.reference_prompts_block
    assert "learned-bad" not in context.reference_prompts_block
    assert "learned-bad" not in context.reference_template_ids


def test_build_user_message_omits_empty_context_sections() -> None:
    """Empty context blocks should not inflate the improver user prompt."""
    context = ImproveContext()
    resolved = resolve_cursor_mode("edit_file", "fix bug")
    message = _build_user_message("fix bug", resolved, context)
    assert "Cursor mode: agent" in message
    assert "Recent conversation:" not in message
    assert "Project facts:" not in message
    assert "Reference prompts:" not in message
    assert "Text:\nfix bug" in message


def test_build_user_message_includes_populated_context_sections() -> None:
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

    with patch(
        "ylang.core.engine.litellm.completion", return_value=mock_response
    ) as mocked:
        improver.improve(
            "fix teh bug", "edit_file", model="test-model", context=context
        )

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
