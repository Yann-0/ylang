"""Candidate evaluation: static inspection and local simulated execution."""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Protocol

from ylang.core.types import CompletionResult, Message
from ylang.importer.normalize import content_hash, sha256_text
from ylang.importer.source_store import PromptSourceStore
from ylang.importer.source_types import EvaluationRun, SourceItem, utcnow_iso
from ylang.library.store import Library
from ylang.usage.experiments import ExperimentStore, ExperimentVariant
from ylang.usage.store import UsageWindow

if TYPE_CHECKING:
    from ylang.core.bounded_completion import PreparedAttempt
    from ylang.usage.hard_budget import Reservation
    from ylang.usage.store import UsageRecord, UsageStore

MIN_OUTCOME_SAMPLES = 3

OutcomeStatus = Literal["improved", "regressed", "unchanged", "pending"]
AttributionKind = Literal["versioned", "mixed", "unknown"]


class EvaluationAuthorizationError(ValueError):
    """Raised when execute is requested without authorization or budget."""


class Completer(Protocol):
    """Engine-shaped completion used by bounded evaluation."""

    def complete(
        self,
        messages: list[Message],
        activity: str,
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        template_version: int | None = None,
    ) -> CompletionResult:
        """Run one completion. Evaluation callers must pass ``tools=None``."""
        ...


@dataclass(frozen=True, slots=True)
class TemplateOutcomeSnapshot:
    """Measured local outcomes for one template. Missing stats stay None."""

    template_id: str
    version: int | None
    accept_rate: float | None
    avg_cost: float | None
    avg_latency_ms: float | None
    injections: int
    unversioned_events: int = 0
    attribution: AttributionKind = "unknown"
    observation_since: str | None = None
    observation_until: str | None = None
    confounders: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Local comparison report. Default inspect mode makes zero provider calls.

    Registers an inactive experiment so the comparison is durable, then records
    current-template effectiveness, static candidate triage, and a body diff.
    Completion-without-error is not treated as success.
    """

    experiment_id: str
    candidate_variant: ExperimentVariant
    current_variant: ExperimentVariant | None
    current_template_id: str | None
    current_template_version: int | None
    current_accept_rate: float | None
    current_avg_cost: float | None
    current_avg_latency_ms: float | None
    current_injections: int
    candidate_quality_score: int
    candidate_risk_level: str
    body_diff_ratio: float | None
    fixture_hash: str | None
    fixture_chars: int | None
    note: str
    mode: Literal["inspect", "execute"] = "inspect"
    evidence_class: Literal["observational", "controlled", "simulated"] = "observational"
    attribution: AttributionKind = "unknown"
    unversioned_events: int = 0
    observation_since: str | None = None
    observation_until: str | None = None
    confounders: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromotedOutcomeDelta:
    """Post-promotion effectiveness compared to the promote-time baseline."""

    template_id: str
    version: int
    item_id: str
    baseline_accept_rate: float | None
    current_accept_rate: float | None
    accept_delta: float | None
    cost_delta: float | None
    latency_delta: float | None
    current_injections: int
    status: OutcomeStatus
    evidence_class: Literal["observational", "controlled", "simulated"] = "observational"
    attribution: AttributionKind = "unknown"
    unversioned_events: int = 0
    confounders: tuple[str, ...] = ()
    observation_since: str | None = None
    observation_until: str | None = None


class SimulatedCompleter:
    """Deterministic local completer. Proves mechanics, not prompt quality."""

    def complete(
        self,
        messages: list[Message],
        activity: str,
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        template_version: int | None = None,
    ) -> CompletionResult:
        """Echo a length token. Never issues a network or paid call."""
        if tools:
            msg = "evaluation must not grant tools"
            raise EvaluationAuthorizationError(msg)
        body = "\n".join(message["content"] for message in messages)
        return CompletionResult(
            content=f"[simulated:{activity}:v{template_version or 0}] {len(body)} chars",
            model_used=model or "simulated/local",
            prompt_tokens=max(1, len(body) // 4),
            completion_tokens=8,
            cost=0.0,
            latency_ms=1,
            success=True,
        )


def _parse_template_ids(raw: str | None) -> list[str]:
    from ylang.usage.template_refs import template_ids_from_refs

    return template_ids_from_refs(raw)


def _event_version_for_template(
    raw: str | None,
    template_id: str,
    scalar_version: int | None,
) -> int | None:
    """Resolve the version for one template on a usage row.

    Prefer ``id@version`` in ``improver_context_templates``. Fall back to the
    scalar ``template_version`` column only for a single-id legacy bare-id row.
    """
    from ylang.usage.template_refs import parse_template_refs

    refs = parse_template_refs(raw)
    matched = [(tid, ver) for tid, ver in refs if tid == template_id]
    if not matched:
        return None
    ref_version = matched[0][1]
    if ref_version is not None:
        return ref_version
    if len(refs) == 1 and scalar_version is not None:
        return scalar_version
    return None


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def measure_template(
    library: Library,
    usage_store: UsageStore | None,
    template_id: str,
    *,
    version: int | None = None,
    since: datetime | str | None = None,
    until: datetime | None = None,
) -> TemplateOutcomeSnapshot:
    """Snapshot accept/cost/latency for a local template from existing usage.

    When ``version`` is set, only usage rows whose per-id ref (or legacy scalar
    ``template_version`` for a single bare id) matches count as evidence. Rows
    that mention the template but lack a version stay ``unknown`` and are not
    attached to a newly promoted version.
    """
    template = library.recall(template_id)
    resolved_version = version if version is not None else (
        template.version if template is not None else None
    )
    empty = TemplateOutcomeSnapshot(
        template_id=template_id,
        version=resolved_version,
        accept_rate=None,
        avg_cost=None,
        avg_latency_ms=None,
        injections=0,
        unversioned_events=0,
        attribution="unknown",
    )
    if usage_store is None:
        return empty
    until_dt = until or datetime.now(timezone.utc)
    if since is None:
        window = UsageWindow.all_time(now=until_dt)
        since_dt = window.since
    else:
        since_dt = _parse_iso(since) if isinstance(since, str) else since
        if since_dt >= until_dt:
            until_dt = since_dt + timedelta(seconds=1)
        window = UsageWindow(since=since_dt, until=until_dt)
    rows = usage_store.recall_usage(window)
    versioned: list[UsageRecord] = []
    unversioned = 0
    other_versions = 0
    for row in rows:
        ids = _parse_template_ids(row.improver_context_templates)
        if template_id not in ids:
            continue
        if not row.improver_fired and not str(row.activity).startswith("improve"):
            continue
        event_version = _event_version_for_template(
            row.improver_context_templates,
            template_id,
            row.template_version,
        )
        if event_version is None:
            unversioned += 1
            continue
        if resolved_version is not None and event_version != resolved_version:
            other_versions += 1
            continue
        versioned.append(row)
    confounders: list[str] = []
    if unversioned:
        confounders.append("unversioned_events")
    if other_versions:
        confounders.append("other_template_versions")
    if since is None and version is None:
        confounders.append("all_time_window")
    n = len(versioned)
    attribution: AttributionKind
    if n > 0:
        attribution = "versioned"
    elif unversioned:
        attribution = "unknown"
    else:
        attribution = "unknown"
    if n == 0:
        return TemplateOutcomeSnapshot(
            template_id=template_id,
            version=resolved_version,
            accept_rate=None,
            avg_cost=None,
            avg_latency_ms=None,
            injections=0,
            unversioned_events=unversioned,
            attribution=attribution,
            observation_since=window.since.isoformat(),
            observation_until=window.until.isoformat(),
            confounders=tuple(confounders),
        )
    accepted = sum(1 for row in versioned if row.improver_accepted)
    return TemplateOutcomeSnapshot(
        template_id=template_id,
        version=resolved_version,
        accept_rate=accepted / n,
        avg_cost=sum(row.cost for row in versioned) / n,
        avg_latency_ms=sum(row.latency_ms for row in versioned) / n,
        injections=n,
        unversioned_events=unversioned,
        attribution=attribution,
        observation_since=window.since.isoformat(),
        observation_until=window.until.isoformat(),
        confounders=tuple(confounders),
    )


def measure_template_observational(
    library: Library,
    usage_store: UsageStore | None,
    template_id: str,
) -> TemplateOutcomeSnapshot:
    """All-time trend including unversioned rows. Not comparative evidence."""
    template = library.recall(template_id)
    version = template.version if template is not None else None
    empty = TemplateOutcomeSnapshot(
        template_id=template_id,
        version=version,
        accept_rate=None,
        avg_cost=None,
        avg_latency_ms=None,
        injections=0,
        attribution="mixed",
        confounders=("all_time_window", "unversioned_included"),
    )
    if usage_store is None:
        return empty
    from ylang.usage.improver_analytics import template_effectiveness

    rows = template_effectiveness(usage_store, UsageWindow.all_time(), min_samples=1)
    for row in rows:
        if row.template_id == template_id:
            unversioned = 0
            for event in usage_store.recall_usage(UsageWindow.all_time()):
                ids = _parse_template_ids(event.improver_context_templates)
                if template_id not in ids:
                    continue
                if (
                    _event_version_for_template(
                        event.improver_context_templates,
                        template_id,
                        event.template_version,
                    )
                    is None
                ):
                    unversioned += 1
            confounders = ["all_time_window"]
            if unversioned:
                confounders.append("unversioned_included")
            return TemplateOutcomeSnapshot(
                template_id=template_id,
                version=version,
                accept_rate=row.accept_rate,
                avg_cost=row.avg_cost,
                avg_latency_ms=row.avg_latency_ms,
                injections=row.injections,
                unversioned_events=unversioned,
                attribution="mixed" if unversioned else "mixed",
                observation_since=UsageWindow.all_time().since.isoformat(),
                observation_until=datetime.now(timezone.utc).isoformat(),
                confounders=tuple(confounders),
            )
    return empty


def body_diff_ratio(current_body: str, candidate_body: str) -> float:
    """Return 0.0 when bodies match and 1.0 when they share no overlap."""
    import difflib

    if not current_body and not candidate_body:
        return 0.0
    ratio = difflib.SequenceMatcher(None, current_body, candidate_body).ratio()
    return round(1.0 - ratio, 4)


def classify_outcome_delta(
    *,
    baseline_accept_rate: float | None,
    current_accept_rate: float | None,
    current_injections: int,
    min_samples: int = MIN_OUTCOME_SAMPLES,
    attribution: AttributionKind = "unknown",
    unversioned_events: int = 0,
) -> tuple[OutcomeStatus, float | None]:
    """Classify whether promoted usage improved versus the captured baseline.

    Versioned evidence below ``min_samples``, missing outcomes, or unknown
    attribution stay ``pending``. This is observational, not a quality proof.
    """
    if attribution == "unknown":
        return "pending", None
    if unversioned_events and current_injections < min_samples:
        return "pending", None
    if (
        baseline_accept_rate is None
        or current_accept_rate is None
        or current_injections < min_samples
    ):
        return "pending", None
    delta = round(current_accept_rate - baseline_accept_rate, 4)
    if delta > 0:
        return "improved", delta
    if delta < 0:
        return "regressed", delta
    return "unchanged", delta


def evaluate_candidate(
    item: SourceItem,
    library: Library,
    experiments: ExperimentStore,
    usage_store: UsageStore | None = None,
    *,
    vs_template_id: str | None = None,
    fixture_input: str | None = None,
    source_store: PromptSourceStore | None = None,
) -> CandidateEvaluation:
    """Inspect a candidate vs the current local template without provider calls.

    Untrusted candidate text is never injected into improver retrieval. Optional
    ``fixture_input`` is operator-supplied, stored locally, and never sent to a
    provider in this mode.
    """
    current_id = vs_template_id or item.duplicate_template_id or item.linked_template_id
    experiment_id = f"prompt-candidate:{item.item_id}"
    candidate_variant = experiments.upsert_variant(
        experiment_id=experiment_id,
        variant_id="candidate",
        config_hash=item.content_hash,
        traffic_pct=0.0,
        active=False,
    )
    current_variant: ExperimentVariant | None = None
    snapshot = (
        measure_template_observational(library, usage_store, current_id)
        if current_id
        else None
    )
    current_body = ""
    current_version = snapshot.version if snapshot else None
    if current_id:
        template = library.recall(current_id)
        if template is not None:
            current_variant = experiments.upsert_variant(
                experiment_id=experiment_id,
                variant_id="current",
                config_hash=content_hash(template.body),
                traffic_pct=0.0,
                active=False,
            )
            current_body = template.body
            current_version = template.version
    diff = body_diff_ratio(current_body, item.body) if current_id else None
    fixture_hash: str | None = None
    fixture_chars: int | None = None
    if fixture_input:
        fixture_hash = sha256_text(fixture_input)
        fixture_chars = len(fixture_input)
    note = (
        "Inspect only (zero provider calls). Experiment traffic stays at 0% so "
        "untrusted candidates are not injected into retrieval. Observational "
        "accept/cost/latency is not controlled comparative evidence. Private history "
        "is not sent to a provider. Do not infer quality from completion-without-error."
    )
    report = CandidateEvaluation(
        experiment_id=experiment_id,
        candidate_variant=candidate_variant,
        current_variant=current_variant,
        current_template_id=current_id,
        current_template_version=current_version,
        current_accept_rate=snapshot.accept_rate if snapshot else None,
        current_avg_cost=snapshot.avg_cost if snapshot else None,
        current_avg_latency_ms=snapshot.avg_latency_ms if snapshot else None,
        current_injections=snapshot.injections if snapshot else 0,
        candidate_quality_score=item.quality_score,
        candidate_risk_level=item.risk_level,
        body_diff_ratio=diff,
        fixture_hash=fixture_hash,
        fixture_chars=fixture_chars,
        note=note,
        mode="inspect",
        evidence_class="observational",
        attribution=snapshot.attribution if snapshot else "unknown",
        unversioned_events=snapshot.unversioned_events if snapshot else 0,
        observation_since=snapshot.observation_since if snapshot else None,
        observation_until=snapshot.observation_until if snapshot else None,
        confounders=snapshot.confounders if snapshot else (),
    )
    persist = source_store or PromptSourceStore(experiments._connection)
    persist.save_evaluation_snapshot(
        item_id=item.item_id,
        vs_template_id=current_id,
        vs_template_version=report.current_template_version,
        current_accept_rate=report.current_accept_rate,
        current_avg_cost=report.current_avg_cost,
        current_avg_latency_ms=report.current_avg_latency_ms,
        current_injections=report.current_injections,
        current_body_hash=content_hash(current_body) if current_body else None,
        candidate_content_hash=item.content_hash,
        quality_score=item.quality_score,
        risk_level=item.risk_level,
        body_diff_ratio=diff,
        fixture_hash=fixture_hash,
        fixture_chars=fixture_chars,
        experiment_id=experiment_id,
    )
    persist.save_evaluation_run(
        EvaluationRun(
            run_id=str(uuid.uuid4()),
            item_id=item.item_id,
            mode="inspect",
            evidence_class="observational",
            vs_template_id=current_id,
            vs_template_version=report.current_template_version,
            vs_content_hash=content_hash(current_body) if current_body else None,
            candidate_content_hash=item.content_hash,
            model=None,
            authorized=False,
            budget_usd=0.0,
            cost_usd=0.0,
            baseline_output=None,
            candidate_output=None,
            baseline_error=None,
            candidate_error=None,
            baseline_latency_ms=None,
            candidate_latency_ms=None,
            baseline_prompt_tokens=None,
            candidate_prompt_tokens=None,
            baseline_completion_tokens=None,
            candidate_completion_tokens=None,
            evaluator_json=json.dumps(
                {
                    "verdict": "inspect_only",
                    "quality_claim": False,
                    "attribution": report.attribution,
                    "unversioned_events": report.unversioned_events,
                },
                sort_keys=True,
            ),
            fixture_hash=fixture_hash,
            created_at=utcnow_iso(),
            note=note,
        )
    )
    return report


def execute_candidate_evaluation(
    item: SourceItem,
    library: Library,
    *,
    completer: Completer,
    fixtures: list[str],
    source_store: PromptSourceStore,
    vs_template_id: str | None = None,
    authorize_paid: bool = False,
    budget_usd: float | str | Decimal = 0.0,
    model: str | None = None,
    simulated: bool = False,
) -> EvaluationRun:
    """Reserve matched bounded arms atomically; real providers remain unavailable."""
    from ylang.core.engine import Engine
    from ylang.core.bounded_completion import BoundedEvidenceError
    from ylang.usage.hard_budget import BudgetRefused, usd_to_nanos

    if not fixtures:
        raise EvaluationAuthorizationError("execute requires operator-supplied --fixture-file inputs")
    bounded_engine: Engine | None = None
    budget_nanos = 0
    if not simulated:
        if not authorize_paid:
            raise EvaluationAuthorizationError(
                "execute requires --authorize-paid; default evaluate is inspect (zero paid calls)"
            )
        if isinstance(budget_usd, float) and (not math.isfinite(budget_usd) or budget_usd <= 0):
            raise EvaluationAuthorizationError("execute requires a finite --budget-usd > 0")
        if type(completer) is not Engine:
            raise EvaluationAuthorizationError(
                "Paid evaluation is unavailable without enforceable cost bounds and an exact bounded Engine."
            )
        try:
            if not isinstance(budget_usd, (str, Decimal)):
                raise BudgetRefused("budget authority must be an exact decimal string or Decimal")
            budget_nanos = usd_to_nanos(budget_usd, cap=True)
            if budget_nanos <= 0:
                raise BudgetRefused("execute requires a finite positive decimal --budget-usd")
            if not model:
                raise BudgetRefused("bounded evaluation requires an explicit pinned model")
        except BudgetRefused as exc:
            raise EvaluationAuthorizationError(str(exc)) from exc
        bounded_engine = completer
    elif type(completer) is not SimulatedCompleter:
        raise EvaluationAuthorizationError(
            "Simulated execution requires the built-in local SimulatedCompleter; "
            "a simulated flag cannot authorize another completer."
        )
    current_id = vs_template_id or item.duplicate_template_id or item.linked_template_id
    current_template = library.recall(current_id) if current_id else None
    if current_template is None:
        raise EvaluationAuthorizationError(
            "execute requires a current template (--vs TEMPLATE); inspect remains available"
        )

    fixture_blob = "\n---\n".join(fixtures)
    arms = (
        ("baseline", current_template.body, current_template.version),
        ("candidate", item.body, None),
    )
    messages_by_arm: dict[str, list[Message]] = {
        label: [{"role": "system", "content": body}, {"role": "user", "content": fixture_blob}]
        for label, body, _ in arms
    }
    prepared: dict[str, PreparedAttempt] = {}
    reservations: dict[str, Reservation] = {}
    financial: dict[str, dict[str, object]] = {}
    if bounded_engine is not None:
        try:
            pair = tuple(bounded_engine.prepare_bounded(model or "", messages_by_arm[label]) for label, _, _ in arms)
            held = bounded_engine.reserve_bounded_pair(
                (pair[0], pair[1]), scope_limit_nanos=budget_nanos,
                metadata=tuple({
                    "arm": label, "item_id": item.item_id, "fixture_hash": sha256_text(fixture_blob),
                    "content_hash": content_hash(body), "template_id": current_id if label == "baseline" else None,
                    "template_version": version,
                } for label, body, version in arms),  # type: ignore[arg-type]
            )
            prepared = {label: pair[index] for index, (label, _, _) in enumerate(arms)}
            reservations = {label: held[index] for index, (label, _, _) in enumerate(arms)}
        except (BudgetRefused, ValueError) as exc:
            raise EvaluationAuthorizationError("No arms dispatched: bounded cost bounds/reservation refused: " + str(exc)) from exc

    results: dict[str, CompletionResult | None] = {"baseline": None, "candidate": None}
    errors: dict[str, str | None] = {"baseline": None, "candidate": None}
    attempted: set[str] = set()
    aborted: EvaluationAuthorizationError | None = None
    interruption: BaseException | None = None
    accounting_errors: dict[str, str] = {}
    for label, _, version in arms:
        attempted.add(label)
        try:
            if bounded_engine is not None:
                result = bounded_engine.complete_prepared(
                    prepared[label], reservations[label], activity="improve", template_version=version,
                )
            else:
                result = completer.complete(
                    messages_by_arm[label], "improve", model=model, tools=None, template_version=version,
                )
            results[label] = result
            if not result.success:
                errors[label] = result.error or "completion_failed"
                if bounded_engine is not None:
                    aborted = EvaluationAuthorizationError("bounded execution stopped after " + label + " failure")
                    break
        except BaseException as exc:
            if isinstance(exc, BoundedEvidenceError):
                results[label] = exc.completion
                accounting_errors[label] = exc.accounting_error
            errors[label] = str(exc) or type(exc).__name__
            if isinstance(exc, EvaluationAuthorizationError) or bounded_engine is not None or not isinstance(exc, Exception):
                aborted = EvaluationAuthorizationError(str(exc) or type(exc).__name__)
                if not isinstance(exc, Exception):
                    interruption = exc
                break

    if bounded_engine is not None:
        for label, reservation in reservations.items():
            try:
                state = bounded_engine.bounded_attempt_evidence(reservation)
                if state["state"] == "RESERVED":
                    bounded_engine.cancel_bounded(reservation)
                financial[label] = bounded_engine.bounded_attempt_evidence(reservation)
            except Exception as exc:
                errors[label] = errors[label] or "reservation cleanup/evidence failed: " + type(exc).__name__
                aborted = aborted or EvaluationAuthorizationError("bounded financial evidence requires reconciliation")

    def arm_evidence(label: str) -> dict[str, Any]:
        """Retain exact identities, immutable configuration and unresolved financial liability."""
        result = results[label]
        record = financial.get(label)
        known_cost = result.cost if result is not None else None
        if bounded_engine is not None:
            actual = record.get("actual_cost_nanos") if record else None
            known_cost = int(actual) / 1_000_000_000 if isinstance(actual, int) else None
        return {
            "attempted": label in attempted,
            "success": result.success if result is not None else (False if label in attempted else None),
            "model_used": result.model_used if result is not None else None,
            "trace_id": result.trace_id if result is not None else None,
            "cost_usd": known_cost,
            "latency_ms": result.latency_ms if result is not None else None,
            "prompt_tokens": result.prompt_tokens if result is not None else None,
            "completion_tokens": result.completion_tokens if result is not None else None,
            "error": errors[label],
            "reported_error": result.error if result is not None else None,
            "accounting_error": accounting_errors.get(label),
            "requested_model": prepared[label].quote.model if label in prepared else model,
            "response_received": bool(result is not None and result.model_used),
            "observed_response": (json.loads(str(record["evidence_json"])).get("observed_response")
                                  if record and record.get("evidence_json") else None),
            "effective_generation_settings": json.loads(prepared[label].config_json) if label in prepared else None,
            "reservation": record,
        }

    base, candidate = results["baseline"], results["candidate"]
    baseline_error, candidate_error = errors["baseline"], errors["candidate"]
    verdict = "inconclusive"
    if baseline_error and candidate_error:
        verdict = "both_error"
    elif baseline_error:
        verdict = "baseline_error"
    elif candidate_error:
        verdict = "candidate_error"
    elif base is not None and candidate is not None and base.success and candidate.success:
        verdict = "both_completed"
    confounders = ["simulated_execution"]
    if base is not None and candidate is not None:
        if not base.model_used or not candidate.model_used:
            confounders.append("unknown_actual_model")
        elif base.model_used != candidate.model_used:
            confounders.append("model_mismatch")
    if any(record.get("state") in {"UNCERTAIN", "DISPATCHING"} for record in financial.values()):
        confounders.append("billing_uncertain")
    if any(record.get("state") == "BREACH" for record in financial.values()):
        confounders.append("certified_bound_exceeded")
    if bounded_engine is not None and any(
        result is not None and result.model_used and result.model_used != prepared[label].quote.model
        for label, result in results.items()
    ) and "model_mismatch" not in confounders:
        confounders.append("model_mismatch")
    if accounting_errors:
        confounders.append("accounting_write_failed")
    if aborted is not None:
        confounders.append("aborted_execution")
    total_known_nanos = sum(int(record["actual_cost_nanos"]) for record in financial.values()
                            if isinstance(record.get("actual_cost_nanos"), int))
    evaluator = {
        "verdict": verdict, "quality_claim": False, "quality_improvement_demonstrated": False,
        "comparison_valid": False,
        "comparison_scope": "bounded_simulated_mechanics" if bounded_engine else "simulated_mechanics_only",
        "confounders": confounders,
        "arms": {label: arm_evidence(label) for label in results},
        "aborted": aborted is not None, "abort_reason": str(aborted) if aborted else None,
        "note": "All supported adapters are synthetic. Execution establishes no provider or quality claim.",
        "fixture_count": len(fixtures), "model": model, "tools_granted": False, "promoted": False,
        "paired_before_dispatch": bounded_engine is not None,
        "budget_scope_limit_nanos": budget_nanos if bounded_engine else None,
        "known_cost_nanos": total_known_nanos if bounded_engine else None,
        "billing_total_known": len(financial) == 2 and all(record.get("state") in {"SETTLED", "CANCELLED", "BREACH"}
                                   for record in financial.values()) if bounded_engine else True,
    }
    run = EvaluationRun(
        run_id=str(uuid.uuid4()), item_id=item.item_id, mode="execute", evidence_class="simulated",
        vs_template_id=current_id, vs_template_version=current_template.version,
        vs_content_hash=content_hash(current_template.body), candidate_content_hash=item.content_hash,
        model=model or "simulated/local", authorized=True,
        budget_usd=budget_nanos / 1_000_000_000 if bounded_engine else 0.0,
        cost_usd=(total_known_nanos / 1_000_000_000 if bounded_engine else
                  sum(result.cost for result in results.values() if result is not None)),
        baseline_output=base.content if base else None, candidate_output=candidate.content if candidate else None,
        baseline_error=baseline_error, candidate_error=candidate_error,
        baseline_latency_ms=base.latency_ms if base else None,
        candidate_latency_ms=candidate.latency_ms if candidate else None,
        baseline_prompt_tokens=base.prompt_tokens if base else None,
        candidate_prompt_tokens=candidate.prompt_tokens if candidate else None,
        baseline_completion_tokens=base.completion_tokens if base else None,
        candidate_completion_tokens=candidate.completion_tokens if candidate else None,
        evaluator_json=json.dumps(evaluator, sort_keys=True), fixture_hash=sha256_text(fixture_blob),
        created_at=utcnow_iso(),
        note="Synthetic mechanics only; no real provider, quality claim, promotion or tools. Cost contains known charges only.",
    )
    source_store.save_evaluation_run(run)
    if interruption is not None:
        raise interruption
    if aborted is not None:
        raise EvaluationAuthorizationError(
            f"{aborted}; evidence saved as evaluation run {run.run_id}"
        ) from aborted
    return run
