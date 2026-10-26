"""Offline evaluation safety, execution evidence and terminal-status regressions."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ylang.core.types import CompletionResult, Message
from ylang.importer.evaluate import (
    EvaluationAuthorizationError,
    SimulatedCompleter,
    execute_candidate_evaluation,
)
from ylang.importer.ingest import ingest_parsed_items
from ylang.importer.normalize import content_hash, sha256_text
from ylang.importer.refresh import open_source_store
from ylang.importer.source_store import PromptSourceStore
from ylang.importer.source_types import EvaluationRun, ParsedUpstreamItem, SourceItem
from ylang.library import open_library
from ylang.library.store import Library


@pytest.fixture
def scenario(tmp_path: Path) -> Iterator[tuple[Library, PromptSourceStore, SourceItem]]:
    """Create synthetic library and quarantined candidate data only."""
    library = open_library(tmp_path / "evaluation.db")
    store = open_source_store(library)
    source = store.get_source("prompts-chat")
    assert source is not None
    ingest_parsed_items(
        store, library, source,
        [ParsedUpstreamItem("safety", "Safety fixture", "Synthetic candidate.")],
        revision="synthetic-evaluation", mark_removed=False,
    )
    library.save(
        "baseline", name="Baseline", body="Synthetic baseline.",
        params=[], source="user", visibility="private",
    )
    item = store.get_item("prompts-chat:safety")
    assert item is not None
    try:
        yield library, store, item
    finally:
        library.close()


def result(
    *, model: str = "simulated/actual", trace: str | None = "synthetic-trace",
    success: bool = True, error: str | None = None, content: str = "Synthetic output",
) -> CompletionResult:
    """Supply deterministic result metadata without provider access."""
    return CompletionResult(
        content=content, model_used=model, prompt_tokens=0, completion_tokens=0,
        cost=0.0, latency_ms=0, success=success, error=error, trace_id=trace,
    )


def run_simulated(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    **overrides: Any,
) -> EvaluationRun:
    """Exercise only the built-in simulator against private fixtures."""
    library, store, item = scenario
    arguments: dict[str, Any] = {
        "completer": SimulatedCompleter(), "fixtures": ["Synthetic fixture"],
        "source_store": store, "vs_template_id": "baseline", "simulated": True,
    }
    arguments.update(overrides)
    return execute_candidate_evaluation(item, library, **arguments)


def install_results(
    monkeypatch: pytest.MonkeyPatch,
    values: list[CompletionResult | Exception],
) -> list[dict[str, Any]]:
    """Inject synthetic failures/results into the built-in local simulator."""
    calls: list[dict[str, Any]] = []

    def complete(
        self: SimulatedCompleter, messages: list[Message], activity: str,
        **kwargs: Any,
    ) -> CompletionResult:
        calls.append({"messages": messages, "activity": activity, **kwargs})
        value = values[len(calls) - 1]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(SimulatedCompleter, "complete", complete)
    return calls


@pytest.mark.parametrize("budget", [0.0, -1.0, float("nan"), float("inf"), -float("inf")])
def test_invalid_paid_budget_rejected_before_completion(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch, budget: float,
) -> None:
    """Invalid budgets must fail before even the local completion stub is called."""
    calls = install_results(monkeypatch, [result(), result()])
    with pytest.raises(EvaluationAuthorizationError):
        run_simulated(scenario, simulated=False, authorize_paid=True, budget_usd=budget)
    assert calls == []


def test_authorization_is_required_before_any_paid_completion(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paid authorization remains a distinct prerequisite."""
    calls = install_results(monkeypatch, [result(), result()])
    with pytest.raises(EvaluationAuthorizationError, match="authorize-paid"):
        run_simulated(scenario, simulated=False, authorize_paid=False, budget_usd=1.0)
    assert calls == []


def test_authorized_paid_execution_fails_closed_without_cost_bounds(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid positive budgets cannot enable the currently unbounded paid runner."""
    calls = install_results(monkeypatch, [result(), result()])
    with pytest.raises(EvaluationAuthorizationError, match="cost bounds"):
        run_simulated(scenario, simulated=False, authorize_paid=True, budget_usd=0.01)
    assert calls == []
    assert scenario[1].list_evaluation_runs(scenario[2].item_id) == []


def test_simulated_flag_cannot_dispatch_an_engine_shaped_completer(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
) -> None:
    """Marking an arbitrary live-capable completer simulated must not bypass the gate."""
    class LiveCapableCompleter:
        """Stand in for a live Engine without actually making provider requests."""

        calls = 0

        def complete(self, *_args: Any, **_kwargs: Any) -> CompletionResult:
            """Count an unsafe dispatch if the simulator gate fails."""
            self.calls += 1
            return result()

    live = LiveCapableCompleter()
    with pytest.raises(EvaluationAuthorizationError, match="built-in"):
        run_simulated(scenario, completer=live)
    assert live.calls == 0


def test_builtin_simulator_preserves_safe_mode_and_quarantine(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
) -> None:
    """Simulation remains available and cannot establish prompt quality."""
    _, store, item = scenario
    run = run_simulated(scenario)
    payload = json.loads(run.evaluator_json)
    assert run.evidence_class == "simulated" and run.cost_usd == 0
    assert payload["verdict"] == "both_completed"
    assert payload["quality_claim"] is False
    assert payload["quality_improvement_demonstrated"] is False
    assert payload["comparison_valid"] is False
    assert "simulated_execution" in payload["confounders"]
    assert payload["tools_granted"] is False and payload["promoted"] is False
    current = store.get_item(item.item_id)
    assert current is not None and current.candidate_state == item.candidate_state


def test_actual_execution_identity_and_zero_metrics_are_retained(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Actual response identity stays distinct from a requested model or alias."""
    calls = install_results(monkeypatch, [
        result(model="simulated/actual", trace="trace-baseline"),
        result(model="simulated/actual", trace="trace-candidate"),
    ])
    run = run_simulated(scenario, model="simulated/requested")
    arms = json.loads(run.evaluator_json)["arms"]
    for name, trace in (("baseline", "trace-baseline"), ("candidate", "trace-candidate")):
        assert arms[name]["model_used"] == "simulated/actual"
        assert arms[name]["trace_id"] == trace
        assert arms[name]["success"] is True and arms[name]["attempted"] is True
        assert arms[name]["cost_usd"] == 0
        assert arms[name]["prompt_tokens"] == arms[name]["completion_tokens"] == 0
        assert arms[name]["latency_ms"] == 0
    assert run.model == "simulated/requested"
    assert run.baseline_prompt_tokens == run.candidate_prompt_tokens == 0
    assert run.baseline_latency_ms == run.candidate_latency_ms == 0
    assert all(call["tools"] is None for call in calls)


def test_different_actual_models_are_explicit_confounders(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operational completion does not imply a fair comparison across model changes."""
    install_results(monkeypatch, [result(model="simulated/a"), result(model="simulated/b")])
    run = run_simulated(scenario)
    payload = json.loads(run.evaluator_json)
    assert payload["verdict"] == "both_completed"
    assert payload["comparison_valid"] is False
    assert "model_mismatch" in payload["confounders"]


@pytest.mark.parametrize("error", [None, ""])
def test_explicit_unsuccessful_results_are_failures_even_without_text(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch, error: str | None,
) -> None:
    """A failed result cannot become successful merely because its error text is empty."""
    install_results(monkeypatch, [
        result(success=False, error=error, content=""),
        result(success=False, error=error, content=""),
    ])
    run = run_simulated(scenario)
    assert run.baseline_output == run.candidate_output == ""
    assert run.baseline_error and run.candidate_error
    assert json.loads(run.evaluator_json)["verdict"] == "both_error"


def test_success_flag_takes_precedence_over_diagnostic_error_text(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve raw diagnostics without misclassifying explicitly successful results."""
    install_results(monkeypatch, [result(error="prior attempt diagnostic"), result()])
    run = run_simulated(scenario)
    payload = json.loads(run.evaluator_json)
    assert run.baseline_error is None
    assert payload["verdict"] == "both_completed"
    assert payload["arms"]["baseline"]["reported_error"] == "prior attempt diagnostic"


def test_empty_exception_text_remains_a_recorded_failure(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception with no message still yields a durable failure status."""
    install_results(monkeypatch, [RuntimeError(), result()])
    run = run_simulated(scenario)
    payload = json.loads(run.evaluator_json)
    assert run.baseline_error == "RuntimeError"
    assert payload["verdict"] == "baseline_error"
    assert payload["arms"]["baseline"]["attempted"] is True
    assert payload["arms"]["baseline"]["success"] is False


@pytest.mark.parametrize("abort_arm", ["baseline", "candidate"])
def test_authorization_abort_retains_partial_evidence_before_reraising(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch, abort_arm: str,
) -> None:
    """An aborted attempted run stays inspectable and unattempted arms remain distinct."""
    values: list[CompletionResult | Exception] = [
        EvaluationAuthorizationError("synthetic abort"),
    ]
    if abort_arm == "candidate":
        values.insert(0, result(trace="retained-baseline"))
    calls = install_results(monkeypatch, values)
    with pytest.raises(EvaluationAuthorizationError, match="synthetic abort") as caught:
        run_simulated(scenario)
    _, store, item = scenario
    saved = store.list_evaluation_runs(item.item_id)
    assert len(saved) == 1
    run = saved[0]
    payload = json.loads(run.evaluator_json)
    assert run.run_id in str(caught.value)
    assert payload["aborted"] is True
    assert payload["arms"][abort_arm]["error"] == "synthetic abort"
    assert len(calls) == (1 if abort_arm == "baseline" else 2)
    if abort_arm == "baseline":
        assert payload["arms"]["candidate"]["attempted"] is False
    else:
        assert run.baseline_output == "Synthetic output"
        assert payload["arms"]["baseline"]["trace_id"] == "retained-baseline"


def test_fixture_hash_and_exact_baseline_version_are_preserved(
    scenario: tuple[Library, PromptSourceStore, SourceItem],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hardening patch must retain matched fixtures and exact template attribution."""
    library, _, item = scenario
    library.save(
        "baseline", name="Baseline", body="Synthetic baseline version two.",
        params=[], source="user", visibility="private",
    )
    template = library.recall("baseline")
    assert template is not None and template.version == 2
    calls = install_results(monkeypatch, [result(), result()])
    run = run_simulated(scenario, fixtures=["First fixture", "Second fixture"])
    assert run.vs_template_version == template.version
    assert run.vs_content_hash == content_hash(template.body)
    assert run.candidate_content_hash == item.content_hash
    assert run.fixture_hash == sha256_text("First fixture\n---\nSecond fixture")
    assert calls[0]["messages"][1] == calls[1]["messages"][1]
    assert calls[0]["template_version"] == 2
    assert calls[1]["template_version"] is None
