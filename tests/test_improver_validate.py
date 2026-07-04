"""Unit tests for improver validation guardrails."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ylang.core.engine import Engine
from ylang.improver.improver import Improver, _validate
from ylang.improver.registry import resolve_cursor_mode
from ylang.improver.types import Change
from ylang.usage.store import open_store

_AGENT = resolve_cursor_mode("edit_file", "test prompt")


@pytest.fixture
def improver(tmp_path: object) -> Improver:
    store = open_store(tmp_path / "test.db")  # type: ignore[operator]
    engine = Engine(store, surface="test")
    return Improver(engine)


def test_validate_accepts_clean_improvement() -> None:
    original = "fix teh bug in main.py"
    improved = "fix the bug in main.py"
    changes = [
        Change(kind="clarity", description="spelling", before="teh", after="the"),
    ]
    result, ok = _validate(original, improved, changes, False, resolved=_AGENT)
    assert ok is True
    assert result.improved == improved
    assert len(result.changes) == 1


def test_validate_accepts_improved_when_changes_incomplete() -> None:
    """Accept improved text when model omits some fixes from changes[] (replay mismatch)."""
    original = "build all remaining backlog items. itterate untill all of them are done and green"
    improved = (
        "Build all remaining backlog items. Iterate until all of them are done and green."
    )
    changes = [
        Change(kind="clarity", description="capitalize", before="build", after="Build"),
        Change(kind="clarity", description="spelling", before="itterate", after="Iterate"),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert result.improved == improved
    assert "until" in result.improved
    assert "untill" not in result.improved


def test_validate_accepts_scope_expansion() -> None:
    original = "build all remaining backlog items"
    improved = (
        "## Goal\nbuild all remaining backlog items\n\n"
        "## Definition of done\n- All tests pass\n- Docs updated"
    )
    changes = [
        Change(
            kind="scope",
            description="Expand to full spec with test and docs scope",
            before=original,
            after=improved,
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert "tests pass" in result.improved.lower()
    assert "docs" in result.improved.lower()


def test_validate_accepts_short_vague_scope_expansion() -> None:
    original = "what shall we do next?"
    improved = (
        "## Goal\nDetermine the next priority work items.\n\n"
        "## Deliverables\n- Ranked list of next actions with rationale\n\n"
        "## Definition of done\n- Clear recommendation ready to execute"
    )
    changes = [
        Change(
            kind="scope",
            description="Expand vague planning question into a full spec",
            before=original,
            after=improved,
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert result.improved == improved
    assert result.changes


def test_validate_accepts_duplicate_number_mentions() -> None:
    original = "Run 1001 unit tests after Wave 18 migration."
    improved = (
        "## Test plan\n"
        "- Run 1001 unit tests (baseline)\n"
        "- Wave 18 migration already complete\n"
        "- Re-run 1001 unit tests before deploy"
    )
    changes = [
        Change(
            kind="scope",
            description="Add structured test plan with repeated baseline count",
            before=original,
            after=improved,
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert "1001" in result.improved


def test_validate_accepts_reformatted_api_migration_prompt() -> None:
    original = (
        "Fix remaining @/lib/supabase-new imports in src/app/api/** routes. "
        "These are service-only imports (AccessCodeService, JobService) — not direct DB access. "
        "Wave 18 already migrated admin calls to @/lib/db-admin. "
        "1001 unit tests passing, deploy via scripts/docker-redeploy-web.sh."
    )
    improved = (
        "## Goal\nFix remaining @/lib/supabase-new imports in src/app/api/** routes.\n\n"
        "## Constraints\n- Service-only imports — not direct DB access\n"
        "- Wave 18 already migrated admin calls to @/lib/db-admin\n\n"
        "## Test plan\n- Run 1001 unit tests\n- Deploy via scripts/docker-redeploy-web.sh"
    )
    changes = [
        Change(
            kind="scope",
            description="Restructure into full spec",
            before=original,
            after=improved,
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert result.improved.startswith("## Goal")


def test_validate_accepts_long_format_restructure() -> None:
    """Format rewrites of medium prompts may grow 5–10x into full specs."""
    original = (
        "Propose next steps for QuickCards after Wave 18 (migrated ~117 API routes). "
        "Wave 19 started on repository imports. 1001 unit tests passing. "
        "Deploy via scripts/docker-redeploy-web.sh."
    )
    improved = (
        "## Goal\nPropose next steps for QuickCards after Wave 18.\n\n"
        "## Current state\n"
        "- Wave 18: migrated ~117 API routes\n"
        "- Wave 19: repository imports in progress\n"
        "- 1001 unit tests passing\n\n"
        "## Deliverables\n"
        "- Ranked backlog for Wave 19+\n"
        "- Risk notes and dependencies\n\n"
        "## Test plan\n"
        "- Run 1001 unit tests\n"
        "- Deploy via scripts/docker-redeploy-web.sh\n\n"
        "## Definition of done\n"
        "- Actionable roadmap with priorities and estimates"
    )
    changes = [
        Change(
            kind="format",
            description="Restructure into full spec sections",
            before=original,
            after=improved,
        ),
    ]
    ratio = len(improved) / len(original)
    assert ratio > 1.5
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert result.validated is True
    assert len(result.changes) == 1
    assert result.improved.startswith("## Goal")


def test_validate_salvage_accepts_restructured_spec() -> None:
    from ylang.improver.improver import _try_salvage

    original = "Propose next steps. Wave 18 done. 1001 tests passing."
    improved = (
        "## Goal\nPropose next steps.\n\n"
        "## Context\n- Wave 18 done\n- 1001 tests passing\n\n"
        "## Definition of done\n- Prioritized roadmap"
    )
    salvaged = _try_salvage(original, improved, True, resolved=_AGENT)
    assert salvaged is not None
    assert salvaged.validated is True
    assert salvaged.improved == improved
    assert len(salvaged.changes) == 1


def test_validate_accepts_comma_formatted_test_count() -> None:
    original = "1001 unit tests passing after Wave 18."
    improved = (
        "## Test plan\n"
        "- Run 1,001 unit tests (baseline)\n"
        "- Wave 18 migration complete"
    )
    changes = [
        Change(
            kind="scope",
            description="Add test plan",
            before=original,
            after=improved,
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True


def test_validate_rejects_improved_without_changes() -> None:
    original = "fix teh bug"
    improved = "fix the bug"
    result, ok = _validate(original, improved, [], False, resolved=_AGENT)
    assert ok is False
    assert result.improved == original
    assert result.rejection_reason == "improved text changed but changes[] is empty"


def test_validate_salvage_accepts_long_agent_expansion_without_changes() -> None:
    from ylang.improver.improver import _try_salvage

    original = (
        "on level up: also from one level to another it seems that I can select "
        "several time the same skills, spells etc check if it's normal if not hide "
        "options already seleced. I want the player to be able to selectec several "
        "options every 2 levels at least. fix all issues and do a deep dive analysis."
    )
    improved = (
        "## Goal\n"
        "Fix level-up selection so duplicate picks are handled correctly and players "
        "gain versatility every 2 levels.\n\n"
        "## Deliverables\n"
        "- Audit level-up skill/spell selection across all classes\n"
        "- Hide or allow duplicate selections based on intended rules\n"
        "- Support multi-rank skill mastery progression\n\n"
        "## Analysis\n"
        "Deep dive on level-up mechanics from one level to another."
    )
    salvaged = _try_salvage(original, improved, True, resolved=_AGENT)
    assert salvaged is not None
    assert salvaged.validated is True
    assert salvaged.improved == improved


def test_intent_preserved_accepts_word_overlap_for_long_prompts() -> None:
    from ylang.improver.improver import _intent_preserved

    original = "fix level up skill selection for all classes every 2 levels deep dive"
    improved = (
        "## Goal\nFix level up skill selection for all classes.\n"
        "## Deliverables\n- Deep dive analysis every 2 levels"
    )
    assert _intent_preserved(original, improved) is True


def test_quoted_spans_ignore_apostrophe_contractions() -> None:
    from ylang.improver.improver import _extract_quoted_spans, _quoted_spans_preserved

    original = (
        "check if it's normal and it's applied to all classes. "
        "Use 'hide duplicate' when needed."
    )
    assert _extract_quoted_spans(original) == ["'hide duplicate'"]
    improved = "## Goal\nEnsure it's normal to hide duplicate selections."
    assert _quoted_spans_preserved(original, improved) is False
    improved_ok = "## Goal\nUse 'hide duplicate' when it's normal."
    assert _quoted_spans_preserved(original, improved_ok) is True


def test_numbers_ignore_iso_timestamps_and_html_comments() -> None:
    from ylang.improver.improver import _numbers_preserved

    original = (
        "<!-- ylang-auto-improve generated=2026-07-04T03:25:23.705608+00:00 -->\n"
        "fix optional tasks detected every 2 levels"
    )
    improved = (
        "## Goal\nFix optional tasks detected every 2 levels.\n"
        "## Deliverables\n- Patch detection rules"
    )
    assert _numbers_preserved(original, improved) is True


def test_numbers_ignore_file_reference_line_ranges() -> None:
    from ylang.improver.improver import _numbers_preserved

    original = r"@terminals\8.txt:7-31"
    improved = (
        "## Goal\nReview terminal output and confirm gateway tests pass.\n"
        "## Deliverables\n- Summarize ruff and pytest results"
    )
    assert _numbers_preserved(original, improved) is True


def test_improver_skips_reference_only_prompt(improver: Improver) -> None:
    with patch("ylang.core.engine.litellm.completion") as mock_completion:
        result = improver.improve(
            r"@\home\yann\.cursor\projects\srv-ylang\terminals\8.txt:7-31",
            "edit_file",
            model="test-model",
        )
    mock_completion.assert_not_called()
    assert result.validated is True
    assert result.improved == result.original
    assert result.changes == []


def test_validate_rejects_number_change() -> None:
    original = "process 42 items"
    improved = "process 43 items"
    changes = [
        Change(kind="clarity", description="typo", before="42", after="43"),
    ]
    result, ok = _validate(original, improved, changes, False, resolved=_AGENT)
    assert ok is False
    assert result.improved == original
    assert result.changes == []


def test_validate_rejects_modal_change() -> None:
    original = "you must run tests"
    improved = "you should run tests"
    changes = [
        Change(kind="clarity", description="soften", before="must", after="should"),
    ]
    result, ok = _validate(original, improved, changes, False, resolved=_AGENT)
    assert ok is False


def test_validate_rejects_before_not_in_original() -> None:
    original = "hello world"
    improved = "hello universe"
    changes = [
        Change(kind="clarity", description="swap", before="galaxy", after="universe"),
    ]
    result, ok = _validate(original, improved, changes, False, resolved=_AGENT)
    assert ok is False


def test_validate_rejects_excessive_length_change() -> None:
    original = "short prompt"
    improved = "short prompt" + (" extra" * 400)
    changes = [
        Change(kind="format", description="pad", before=original, after=improved),
    ]
    result, ok = _validate(original, improved, changes, False, resolved=_AGENT)
    assert ok is False
    assert result.rejection_reason == "length ratio out of bounds"


def test_validate_accepts_short_clarity_condensation() -> None:
    """Informal prefix removal on short prompts must not fail length ratio."""
    original = "let's do all"
    improved = "do all"
    changes = [
        Change(
            kind="clarity",
            description="Remove informal prefix",
            before="let's ",
            after="",
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert result.validated is True
    assert result.improved == improved


def test_fallback_short_prompt_expansion_multitask() -> None:
    from ylang.improver.improver import _fallback_short_prompt_expansion, _is_vague_short_prompt

    original = "let's do all"
    assert _is_vague_short_prompt(original) is True
    resolved = resolve_cursor_mode("cursor-multitask", original, explicit_mode="multitask")
    result = _fallback_short_prompt_expansion(original, True, resolved=resolved, require_vague=True)
    assert result is not None
    assert result.validated is True
    assert result.improved.startswith("## Goal")
    assert "let's do all" in result.improved
    assert "## Workstreams" in result.improved
    assert _fallback_short_prompt_expansion(
        "process 42 items",
        True,
        resolved=resolved,
        require_vague=True,
    ) is None


def test_validate_accepts_short_prompt_spec_expansion() -> None:
    original = "fix optional tasks detected"
    improved = (
        "## Goal\nFix optional tasks incorrectly flagged as required.\n\n"
        "## Workstreams\n"
        "1. Reproduce false positives in detection pipeline\n"
        "2. Patch rules and add regression tests\n\n"
        "## Definition of done\n"
        "- Optional tasks no longer auto-detected incorrectly"
    )
    changes = [
        Change(
            kind="scope",
            description="Expand into multitask spec",
            before=original,
            after=improved,
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert result.validated is True
    assert result.improved.startswith("## Goal")


def test_improver_salvages_improved_only_broken_json(improver: Improver) -> None:
    """Regression: broken JSON with improved but no changes[] must not fail parse."""
    original = (
        "Implement the plan as specified, it is attached for your reference. "
        "Do NOT edit the plan file itself."
    )
    raw = """{
  "improved": "## Goal
Implement the plan exactly as written in the attached plan file.

## Deliverables
- Complete all plan to-dos without editing the plan file"
}"""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=raw))]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve(original, "cursor-agent", model="test-model")

    assert result.validated is True
    assert result.rejection_reason is None
    assert "Implement the plan" in result.improved
    assert len(result.changes) == 1
    assert result.changes[0].kind == "scope"


def test_improver_salvages_plain_markdown_model_output(improver: Improver) -> None:
    original = (
        "ok ensure it's fully documented for priorisation and other confguration "
        "(not specificaly linked to mistral)"
    )
    plain = (
        "## Goal\n"
        "Ensure prioritisation and general Ylang configuration are fully documented.\n\n"
        "## Deliverables\n"
        "- Expand docs/configuration.md\n\n"
        "## Definition of done\n"
        "- All YLANG_MODELS_* vars documented"
    )
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=plain))]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve(original, "Cursor", model="test-model")

    assert result.validated is True
    assert result.improved.startswith("## Goal")
    assert result.rejection_reason is None


def test_improver_expands_unchanged_short_prompt(improver: Improver) -> None:
    original = "let's do all"
    payload = {"improved": original, "changes": []}
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(payload)))
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve(
            original,
            "cursor-multitask",
            model="test-model",
            mode="multitask",
        )

    assert result.validated is True
    assert result.improved.startswith("## Goal")
    assert "## Workstreams" in result.improved
    assert original in result.improved


def test_improver_fallback_after_validation_rejection(improver: Improver) -> None:
    original = "let's do all"
    payload = {
        "improved": "x" * 5000,
        "changes": [
            {
                "kind": "scope",
                "description": "Over-expanded",
                "before": original,
                "after": "x" * 5000,
            }
        ],
    }
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(payload)))
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve(
            original,
            "cursor-multitask",
            model="test-model",
            mode="multitask",
        )

    assert result.validated is True
    assert result.rejection_reason is None
    assert result.improved.startswith("## Goal")
    assert len(result.improved) < 500


def test_improver_llm_failure_returns_safe_result(improver: Improver) -> None:
    with patch("ylang.core.engine.litellm.completion", side_effect=RuntimeError("down")):
        result = improver.improve("hello", "edit_file", model="openai/gpt-4o")
    assert result.original == "hello"
    assert result.improved == "hello"
    assert result.changes == []
    assert result.auto_apply_default is False


def test_improver_validation_rejection_returns_safe_result(improver: Improver) -> None:
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "improved": "process 99 items",
                        "changes": [
                            {
                                "kind": "clarity",
                                "description": "bad",
                                "before": "42",
                                "after": "99",
                            }
                        ],
                    }
                )
            )
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve("process 42 items", "edit_file", model="test-model")
    assert result.improved == "process 42 items"
    assert result.changes == []
    assert result.validated is False
    assert result.rejection_reason == "numbers changed"


def test_auto_apply_false_for_precision_tools(improver: Improver) -> None:
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({"improved": "ok", "changes": []})))
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve("ok", "edit_file", model="test-model")
    assert result.auto_apply_default is False


def test_auto_apply_true_for_non_precision_tools(improver: Improver) -> None:
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({"improved": "ok", "changes": []})))
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve("ok", "cursor-agent", model="test-model")
    assert result.auto_apply_default is True


def test_improver_records_accepted_when_validated_and_changed(improver: Improver) -> None:
    original = "fix teh bug"
    payload = {
        "improved": "fix the bug",
        "changes": [
            {
                "kind": "clarity",
                "description": "spelling",
                "before": "teh",
                "after": "the",
            }
        ],
    }
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(payload)))
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve(original, "edit_file", model="test-model")

    assert result.validated is True
    from ylang.usage.store import UsageWindow

    rows = improver._engine.store.recall_usage(UsageWindow.last_hours(1))
    assert len(rows) == 1
    assert rows[0].improver_accepted is True


def test_improver_accepted_param_logged_on_complete(improver: Improver) -> None:
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({"improved": "hello", "changes": []})))
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        improver.improve("hello", "edit_file", model="test-model", accepted=True)

    from ylang.usage.store import UsageWindow

    rows = improver._engine.store.recall_usage(UsageWindow.last_hours(1))
    assert rows[0].improver_accepted is True
