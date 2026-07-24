"""Unit tests for improver validation guardrails."""

from __future__ import annotations

import json
import threading
import time
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
    improved = "Build all remaining backlog items. Iterate until all of them are done and green."
    changes = [
        Change(kind="clarity", description="capitalize", before="build", after="Build"),
        Change(
            kind="clarity", description="spelling", before="itterate", after="Iterate"
        ),
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
        "## Test plan\n- Run 1,001 unit tests (baseline)\n- Wave 18 migration complete"
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


def test_validate_salvages_numbers_changed_list_renumbering() -> None:
    """Restructuring that drops list-marker indices must not fail numbers changed."""
    original = (
        "my answers\n"
        "1. I do not understand what is the purpose. explain\n"
        "2. 5\n"
        "3. both\n"
        "4. per party"
    )
    improved = (
        "## Goal\nClarify quiz answers including the value 5.\n\n"
        "## Deliverables\n"
        "- Explain the purpose\n"
        "- Confirm answer 5, both, and per party"
    )
    changes = [
        Change(
            kind="format",
            description="Restructure answers into spec",
            before=original,
            after=improved,
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert result.validated is True


def test_try_salvage_validation_failure_numbers_changed() -> None:
    from ylang.improver.improver import _try_salvage_validation_failure

    original = "Wave 18 follow-up:\n1. Run tests\n2. Deploy"
    improved = (
        "## Goal\nComplete Wave 18 follow-up.\n\n"
        "## Workstreams\n- Run tests\n- Deploy"
    )
    changes = [
        Change(
            kind="format",
            description="Restructure",
            before=original,
            after=improved,
        ),
    ]
    salvaged = _try_salvage_validation_failure(
        original,
        improved,
        changes,
        True,
        resolved=_AGENT,
        rejection_reason="numbers changed",
    )
    assert salvaged is not None
    assert salvaged.validated is True
    assert salvaged.improved == improved


def test_validate_salvages_minor_clarity_without_changes() -> None:
    original = "fix teh bug"
    improved = "fix the bug"
    result, ok = _validate(original, improved, [], False, resolved=_AGENT)
    assert ok is True
    assert result.improved == improved
    assert result.validated is True
    assert len(result.changes) == 1


def test_validate_salvages_restructured_spec_with_omitted_changes() -> None:
    original = (
        "we need to use AI to generate real possible answers (even false) and do not take "
        "answers totaly out of the context of the question and taken from other questions. "
        "it must be realistic.\n\n"
        "each question can allow this type of answeres :\n"
        "- a single option from 2 to 4 possible and relatisc values related to the question, "
        "using radio button\n"
        "- up to 2 to 4 answers (precise the number of valid answers expected) using checkbox"
    )
    improved = (
        "## Goal\n"
        "Use AI to generate realistic quiz answer options that stay in question context.\n\n"
        "## Deliverables\n"
        "- Single-choice questions: 2 to 4 radio options per question\n"
        "- Multiple-choice questions: 2 to 4 checkbox options with explicit valid-answer count\n\n"
        "## Constraints\n"
        "- Distractors must be plausible but false; never reuse answers from other questions"
    )
    result, ok = _validate(original, improved, [], True, resolved=_AGENT)
    assert ok is True
    assert result.validated is True
    assert result.improved == improved
    assert len(result.changes) == 1
    assert result.rejection_reason is None


def test_validate_salvages_spec_with_duplicate_numbers_consolidated() -> None:
    """Distinct numbers must remain; duplicate mentions in the original may be consolidated."""
    original = "Pick 2 to 4 options. Multiple choice allows 2 to 4 valid answers."
    improved = (
        "## Goal\nPick 2 to 4 options per question.\n\n"
        "## Constraints\n- Multiple choice: 2 to 4 valid answers with explicit count"
    )
    result, ok = _validate(original, improved, [], True, resolved=_AGENT)
    assert ok is True
    assert result.validated is True


def test_is_restructured_spec_accepts_heading_structure_without_large_growth() -> None:
    from ylang.improver.improver import _is_restructured_spec

    original = "x" * 320
    improved = f"## Goal\n{original}\n\n## Deliverables\n- Item one"
    assert _is_restructured_spec(original, improved) is True


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


def test_validate_accepts_whitespace_normalized_before() -> None:
    original = "fix the  bug\nin main.py"
    improved = "fix the bug in main.py"
    changes = [
        Change(
            kind="clarity",
            description="collapse whitespace",
            before="fix the  bug\nin main.py",
            after="fix the bug in main.py",
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert result.improved == improved


def test_validate_accepts_scope_with_paraphrased_before() -> None:
    original = "do a full commit of the remaining work"
    improved = (
        "## Goal\ndo a full commit of the remaining work\n\n"
        "## Deliverables\n- Stage, commit, and push remaining changes\n\n"
        "## Definition of done\n- Clean git status"
    )
    changes = [
        Change(
            kind="scope",
            description="Expand into commit checklist",
            before="full commit of remaining work",
            after=improved,
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is True
    assert result.validated is True


def test_numbers_ignore_ordered_list_markers() -> None:
    from ylang.improver.improver import _numbers_preserved

    original = (
        "my answers\n"
        "1. I do not understand what is the purpose. explain\n"
        "2. 5\n"
        "3. both\n"
        "4. per party"
    )
    improved = (
        "## Goal\nClarify quiz answers including the value 5.\n\n"
        "## Deliverables\n"
        "- Explain the purpose\n"
        "- Confirm answer 5, both, and per party"
    )
    assert _numbers_preserved(original, improved) is True


def test_validate_salvages_anchor_failure_via_omitted_path() -> None:
    """When before anchors fail but improved is a safe restructure, salvage it."""
    from ylang.improver.improver import _try_salvage, _salvage_omitted_changes

    original = "what is the purpose of this screen ?"
    improved = (
        "## Goal\nExplain the purpose of this screen.\n\n"
        "## Deliverables\n- Clear description of screen intent and audience\n\n"
        "## Definition of done\n- Answer ready for the user"
    )
    changes = [
        Change(
            kind="clarity",
            description="bad anchor",
            before="qwerty-unrelated-anchor-zzz",
            after="purpose of this screen",
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is False
    assert result.rejection_reason == "change.before not anchored to original"
    salvaged = _try_salvage(original, improved, True, resolved=_AGENT)
    if salvaged is None:
        salvaged = _salvage_omitted_changes(original, improved, True, resolved=_AGENT)
    assert salvaged is not None
    assert salvaged.validated is True
    assert salvaged.improved == improved


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
    from ylang.improver.improver import (
        _fallback_short_prompt_expansion,
        _is_vague_short_prompt,
    )

    original = "let's do all"
    assert _is_vague_short_prompt(original) is True
    resolved = resolve_cursor_mode(
        "cursor-multitask", original, explicit_mode="multitask"
    )
    result = _fallback_short_prompt_expansion(
        original, True, resolved=resolved, require_vague=True
    )
    assert result is not None
    assert result.validated is True
    assert result.improved.startswith("## Goal")
    assert "let's do all" in result.improved
    assert "## Workstreams" in result.improved
    assert (
        _fallback_short_prompt_expansion(
            "process 42 items",
            True,
            resolved=resolved,
            require_vague=True,
        )
        is None
    )


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
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
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
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
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
    with patch(
        "ylang.core.engine.litellm.completion", side_effect=RuntimeError("down")
    ):
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
        MagicMock(
            message=MagicMock(content=json.dumps({"improved": "ok", "changes": []}))
        )
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
        MagicMock(
            message=MagicMock(content=json.dumps({"improved": "ok", "changes": []}))
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve("ok", "cursor-agent", model="test-model")
    assert result.auto_apply_default is True


def test_improver_salvages_structured_output_with_empty_changes(
    improver: Improver,
) -> None:
    original = (
        "we need to use AI to generate real possible answers (even false) and do not take "
        "answers totaly out of the context of the question. each question can allow "
        "single option from 2 to 4 possible values using radio button or 2 to 4 checkbox answers."
    )
    improved = (
        "## Goal\n"
        "Generate realistic AI quiz distractors that stay in question context.\n\n"
        "## Deliverables\n"
        "- Radio single-choice questions with 2 to 4 options\n"
        "- Checkbox multiple-choice questions with 2 to 4 options and explicit valid count"
    )
    payload = {"improved": improved, "changes": []}
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve(
            original, "cursor-agent", model="test-model", mode="agent"
        )

    assert result.validated is True
    assert result.rejection_reason is None
    assert result.improved == improved
    assert len(result.changes) == 1


def test_improver_records_accepted_when_validated_and_changed(
    improver: Improver,
) -> None:
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
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
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
        MagicMock(
            message=MagicMock(content=json.dumps({"improved": "hello", "changes": []}))
        )
    ]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        improver.improve("hello", "edit_file", model="test-model", accepted=True)

    from ylang.usage.store import UsageWindow

    rows = improver._engine.store.recall_usage(UsageWindow.last_hours(1))
    assert rows[0].improver_accepted is True


def test_improver_timeout_returns_safe_result(
    improver: Improver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Long prompts past the timeout fallback budget still hard-reject."""
    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "0.05")
    long_prompt = "please analyze " + ("the architecture and performance " * 20)

    def slow_complete(*_args: object, **_kwargs: object) -> object:
        import time

        time.sleep(1.0)
        raise AssertionError("should have timed out")

    with patch("ylang.core.engine.litellm.completion", side_effect=slow_complete):
        result = improver.improve(long_prompt, "cursor-agent", model="auto")

    assert result.improved == long_prompt
    assert result.validated is False
    assert result.rejection_reason == "improver timeout"


def test_improver_timeout_salvages_medium_prompt(
    improver: Improver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "0.05")

    def slow_complete(*_args: object, **_kwargs: object) -> object:
        import time

        time.sleep(1.0)
        raise AssertionError("should have timed out")

    with patch("ylang.core.engine.litellm.completion", side_effect=slow_complete):
        result = improver.improve("hello world", "cursor-agent", model="auto")

    assert result.validated is True
    assert "## Goal" in result.improved
    assert "hello world" in result.improved


def test_improver_timeout_salvages_short_prompt(
    improver: Improver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "0.05")

    def slow_complete(*_args: object, **_kwargs: object) -> object:
        import time

        time.sleep(1.0)
        raise AssertionError("should have timed out")

    with patch("ylang.core.engine.litellm.completion", side_effect=slow_complete):
        result = improver.improve("go", "cursor-agent", model="auto")

    assert result.validated is True
    assert result.improved != "go"
    assert "## Goal" in result.improved

    from ylang.usage.store import UsageWindow

    rows = improver._engine.store.recall_usage(UsageWindow.last_hours(1))
    assert len(rows) == 1
    assert rows[0].success is False
    assert rows[0].improver_fired is True
    assert rows[0].improver_validated is True
    assert rows[0].improver_changed is True
    assert rows[0].improver_rejection_reason is None


def test_improver_timeout_returns_safe_result_usage_row(
    improver: Improver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "0.05")
    long_prompt = "please analyze " + ("the architecture and performance " * 20)

    def slow_complete(*_args: object, **_kwargs: object) -> object:
        import time

        time.sleep(1.0)
        raise AssertionError("should have timed out")

    with patch("ylang.core.engine.litellm.completion", side_effect=slow_complete):
        improver.improve(long_prompt, "cursor-agent", model="auto")

    from ylang.usage.store import UsageWindow

    rows = improver._engine.store.recall_usage(UsageWindow.last_hours(1))
    assert len(rows) == 1
    assert rows[0].success is False
    assert rows[0].improver_fired is True
    assert rows[0].improver_rejection_reason == "improver timeout"
    assert rows[0].improver_validated is False


def test_improver_timeout_scrubs_late_success_orphan(
    improver: Improver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Late engine.complete after timeout must not leave a normal success row."""
    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "0.05")
    long_prompt = "please analyze " + ("the architecture and performance " * 20)
    release = threading.Event()

    def blocked_then_ok(*_args: object, **_kwargs: object) -> object:
        release.wait(timeout=2.0)
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({"improved": long_prompt, "changes": []})
                )
            )
        ]
        mock_response.model = "test-model"
        mock_response.usage = MagicMock(prompt_tokens=3, completion_tokens=1)
        mock_response._hidden_params = {"response_cost": 0.01}
        return mock_response

    with patch("ylang.core.engine.litellm.completion", side_effect=blocked_then_ok):
        result = improver.improve(long_prompt, "cursor-agent", model="auto")
        release.set()
        time.sleep(0.3)

    assert result.rejection_reason == "improver timeout"

    from ylang.usage.improver_analytics import summarize_improver
    from ylang.usage.store import UsageWindow

    window = UsageWindow.last_hours(1)
    rows = improver._engine.store.recall_usage(window)
    success_improver = [
        row
        for row in rows
        if row.success and row.improver_fired and row.improver_rejection_reason is None
    ]
    assert success_improver == []
    timeout_rows = [
        row for row in rows if row.improver_rejection_reason == "improver timeout"
    ]
    assert len(timeout_rows) == 1
    funnel = summarize_improver(improver._engine.store, window)
    assert funnel.total_fired == 1
    assert funnel.top_rejection_reasons.get("improver timeout") == 1


def test_improver_skips_critique_near_timeout_budget(
    improver: Improver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YLANG_IMPROVER_TIMEOUT_SEC", "12")
    monkeypatch.setenv("YLANG_IMPROVER_CRITIQUE", "1")
    original = "fix teh bug"
    improved = "fix the bug"
    payload = {
        "improved": improved,
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
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    calls: list[object] = []

    def tracking_complete(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return mock_response

    # First-pass nearly exhausts the budget so critique should be skipped.
    # 1) deadline = monotonic + 12 → 112; 2–3) critique remaining check + log.
    monotonic_values = iter([100.0, 111.5, 111.5])

    with (
        patch("ylang.core.engine.litellm.completion", side_effect=tracking_complete),
        patch(
            "ylang.improver.improver.time.monotonic",
            side_effect=lambda: next(monotonic_values, 111.5),
        ),
    ):
        result = improver.improve(original, "edit_file", model="test-model")

    assert result.improved == improved
    assert len(calls) == 1


def test_improver_salvages_bad_before_anchor(improver: Improver) -> None:
    original = "do the follow-up check list and fix any issues"
    improved = (
        "## Goal\nComplete the follow-up checklist and fix issues.\n\n"
        "## Deliverables\n- Work through each checklist item\n"
        "- Fix failures found during verification\n\n"
        "## Definition of done\n- Checklist complete with evidence"
    )
    payload = {
        "improved": improved,
        "changes": [
            {
                "kind": "clarity",
                "description": "typo",
                "before": "follow up checklist XYZ",
                "after": "follow-up check list",
            }
        ],
    }
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    mock_response.model = "test-model"
    mock_response.usage = MagicMock(prompt_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        result = improver.improve(original, "cursor-agent", model="auto", mode="agent")

    assert result.validated is True
    assert result.rejection_reason is None
    assert result.improved == improved
    assert len(result.changes) == 1
    assert result.changes[0].kind == "scope"


def test_change_before_accepts_fuzzy_anchor() -> None:
    from ylang.improver.improver import _change_before_valid

    original = "fix the authentication middleware timeout bug"
    change = Change(
        kind="clarity",
        description="rephrase",
        before="authentication middleware timeout",
        after="auth middleware timeout",
    )
    assert _change_before_valid(original, change) is True


def test_change_before_accepts_case_insensitive_medium_span() -> None:
    from ylang.improver.improver import _change_before_valid

    original = "Please Fix The Authentication Middleware Timeout In Login"
    change = Change(
        kind="clarity",
        description="normalize casing",
        before="fix the authentication middleware timeout",
        after="fix the authentication middleware timeout",
    )
    assert _change_before_valid(original, change) is True


def test_change_before_medium_fuzzy_salvage_still_rejects_number_edits() -> None:
    from ylang.improver.improver import _validate

    original = "retry the request 3 times then fail"
    improved = "retry the request 5 times then fail"
    changes = [
        Change(
            kind="clarity",
            description="paraphrase with bad number",
            before="Retry The Request 3 Times",
            after="retry the request 5 times",
        ),
    ]
    result, ok = _validate(original, improved, changes, True, resolved=_AGENT)
    assert ok is False
    assert result.rejection_reason == "numbers changed"


def test_empty_changes_salvages_single_heading_expansion() -> None:
    from ylang.improver.improver import _validate

    original = "add dark mode toggle to settings"
    improved = (
        "## Goal\nAdd a dark mode toggle to settings.\n\n"
        "- Persist preference\n"
        "- Update UI chrome"
    )
    result, ok = _validate(original, improved, [], True, resolved=_AGENT)
    assert ok is True
    assert result.validated is True
    assert result.improved == improved
