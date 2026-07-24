"""Unit tests for patterns CLI commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ylang.cli.patterns import run_patterns_cli
from ylang.core.stores import open_stores
from ylang.library.patterns import DetectedPattern, TemplateProposal
from ylang.library.types import TemplateParam
from ylang.usage.store import open_store


def _valid_proposal_for(pattern: DetectedPattern) -> TemplateProposal:
    return TemplateProposal(
        suggested_template_id=f"learned-{pattern.pattern_id}",
        name=f"Learned: {pattern.pattern_id}",
        body=(
            "Refactor the {module} routes for async sqlite access "
            "and add {test_scope} tests."
        ),
        params=[
            TemplateParam(name="module", description="Module", default="gateway"),
            TemplateParam(name="test_scope", description="Scope", default="unit"),
        ],
        rationale="Detected repeated prompts.",
    )


def _mock_valid_proposals(monkeypatch: pytest.MonkeyPatch) -> None:
    def _outcome(pattern: DetectedPattern, *, engine: object | None = None) -> object:
        from ylang.library.patterns import PatternProposalOutcome

        return PatternProposalOutcome(proposal=_valid_proposal_for(pattern))

    monkeypatch.setattr(
        "ylang.cli.patterns.propose_template_from_pattern",
        lambda pattern: _valid_proposal_for(pattern),
    )
    monkeypatch.setattr(
        "ylang.library.pattern_detector.propose_template_from_pattern_outcome",
        _outcome,
    )


def test_patterns_suggest_cli(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "patterns.db"  # type: ignore[operator]
    store = open_store(db_path)
    now = datetime.now(timezone.utc)
    sample = "Add unit tests for the payment module with edge cases"
    for offset in range(3):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="openai/gpt-4o",
            prompt_tokens=50,
            cost=0.01,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=5,
            success=True,
            improver_input_sample=sample,
            timestamp=now - timedelta(days=offset + 1),
        )
    store.close()

    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    _mock_valid_proposals(monkeypatch)
    exit_code = run_patterns_cli(["suggest", "--window-days", "30"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Proposal" in captured.out
    assert "learned-" in captured.out


def test_patterns_suggest_empty(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "empty-patterns.db"  # type: ignore[operator]
    store = open_store(db_path)
    store.close()

    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    exit_code = run_patterns_cli(["suggest"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No patterns detected" in captured.out


def test_patterns_apply_cli(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "apply-patterns.db"  # type: ignore[operator]
    store = open_store(db_path)
    now = datetime.now(timezone.utc)
    sample = "Refactor the gateway routes for async sqlite access"
    for offset in range(3):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="openai/gpt-4o",
            prompt_tokens=50,
            cost=0.01,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=5,
            success=True,
            improver_input_sample=sample,
            timestamp=now - timedelta(days=offset + 1),
        )
    store.close()

    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    _mock_valid_proposals(monkeypatch)
    exit_code = run_patterns_cli(["apply", "--index", "1", "--yes"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Saved learned template" in captured.out

    stores = open_stores(db_path)
    try:
        learned = stores.library.list(source="learned")  # type: ignore[attr-defined]
        assert len(learned) == 1
        template = stores.library.recall(learned[0].template_id)  # type: ignore[attr-defined]
        assert template is not None
        assert template.source == "learned"
    finally:
        stores.close()  # type: ignore[attr-defined]
