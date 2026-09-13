"""Candidate evaluation: static inspect vs bounded Engine execution."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal, Protocol

from ylang.core.types import CompletionResult, Message
from ylang.importer.normalize import content_hash, sha256_text
from ylang.importer.source_store import PromptSourceStore
from ylang.importer.source_types import EvaluationRun, SourceItem, utcnow_iso
from ylang.library.store import Library
from ylang.usage.experiments import ExperimentStore, ExperimentVariant
from ylang.usage.store import UsageWindow

if TYPE_CHECKING:
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
    budget_usd: float = 0.0,
    model: str | None = None,
    simulated: bool = False,
) -> EvaluationRun:
    """Run baseline and candidate on matched fixtures through the Engine.

    Default paid budget is zero. Paid execution requires ``authorize_paid`` and
    ``budget_usd > 0``. Simulated execution proves mechanics only. Tools are
    never granted. This does not promote the candidate.
    """
    if not fixtures:
        raise EvaluationAuthorizationError(
            "execute requires operator-supplied --fixture-file inputs"
        )
    if not simulated and not authorize_paid:
        raise EvaluationAuthorizationError(
            "execute requires --authorize-paid; default evaluate is inspect (zero paid calls)"
        )
    if not simulated and budget_usd <= 0:
        raise EvaluationAuthorizationError(
            "execute requires --budget-usd > 0; default budget is 0"
        )
    current_id = vs_template_id or item.duplicate_template_id or item.linked_template_id
    current_template = library.recall(current_id) if current_id else None
    if current_template is None:
        raise EvaluationAuthorizationError(
            "execute requires a current template (--vs TEMPLATE); inspect remains available"
        )
    fixture_blob = "\n---\n".join(fixtures)
    fixture_hash = sha256_text(fixture_blob)
    cost = 0.0
    baseline_outputs: list[str] = []
    candidate_outputs: list[str] = []
    baseline_error: str | None = None
    candidate_error: str | None = None
    baseline_latency = 0
    candidate_latency = 0
    baseline_prompt = 0
    candidate_prompt = 0
    baseline_completion = 0
    candidate_completion = 0
    activity = "improve"

    def _run(body: str, *, version: int | None, label: str) -> CompletionResult:
        nonlocal cost
        if cost > budget_usd and not simulated:
            raise EvaluationAuthorizationError(
                f"budget exhausted before {label} (spent ${cost:.4f} of ${budget_usd:.4f})"
            )
        messages: list[Message] = [
            {"role": "system", "content": body},
            {"role": "user", "content": fixture_blob},
        ]
        result = completer.complete(
            messages,
            activity,
            model=model,
            tools=None,
            template_version=version,
        )
        cost += result.cost
        if not simulated and cost > budget_usd:
            raise EvaluationAuthorizationError(
                f"budget exceeded during {label} (spent ${cost:.4f} of ${budget_usd:.4f})"
            )
        return result

    try:
        base = _run(current_template.body, version=current_template.version, label="baseline")
        baseline_outputs.append(base.content)
        baseline_error = base.error
        baseline_latency = base.latency_ms
        baseline_prompt = base.prompt_tokens
        baseline_completion = base.completion_tokens
    except EvaluationAuthorizationError:
        raise
    except Exception as exc:  # noqa: BLE001 — capture provider failures as evidence
        baseline_error = str(exc)

    try:
        cand = _run(item.body, version=None, label="candidate")
        candidate_outputs.append(cand.content)
        candidate_error = cand.error
        candidate_latency = cand.latency_ms
        candidate_prompt = cand.prompt_tokens
        candidate_completion = cand.completion_tokens
    except EvaluationAuthorizationError:
        raise
    except Exception as exc:  # noqa: BLE001 — capture provider failures as evidence
        candidate_error = str(exc)

    evidence: Literal["controlled", "simulated"] = (
        "simulated" if simulated else "controlled"
    )
    verdict = "inconclusive"
    if baseline_error and candidate_error:
        verdict = "both_error"
    elif baseline_error:
        verdict = "baseline_error"
    elif candidate_error:
        verdict = "candidate_error"
    elif baseline_outputs and candidate_outputs:
        verdict = "both_completed"
    evaluator = {
        "verdict": verdict,
        "quality_claim": False,
        "quality_improvement_demonstrated": False,
        "note": (
            "Completion-without-error is not success. A working runner does not "
            "prove a prompt is better. Simulated results prove mechanics only."
        ),
        "fixture_count": len(fixtures),
        "model": model,
        "tools_granted": False,
        "promoted": False,
    }
    note = (
        "Bounded Engine execution on operator fixtures. Candidate was not promoted "
        "and was not granted tools. "
        + (
            "Simulated provider: mechanics only, not prompt quality."
            if simulated
            else "Controlled comparative evidence; not an automatic promotion."
        )
    )
    run = EvaluationRun(
        run_id=str(uuid.uuid4()),
        item_id=item.item_id,
        mode="execute",
        evidence_class=evidence,
        vs_template_id=current_id,
        vs_template_version=current_template.version,
        vs_content_hash=content_hash(current_template.body),
        candidate_content_hash=item.content_hash,
        model=model or ("simulated/local" if simulated else None),
        authorized=authorize_paid or simulated,
        budget_usd=0.0 if simulated else budget_usd,
        cost_usd=cost,
        baseline_output="\n".join(baseline_outputs) or None,
        candidate_output="\n".join(candidate_outputs) or None,
        baseline_error=baseline_error,
        candidate_error=candidate_error,
        baseline_latency_ms=baseline_latency or None,
        candidate_latency_ms=candidate_latency or None,
        baseline_prompt_tokens=baseline_prompt or None,
        candidate_prompt_tokens=candidate_prompt or None,
        baseline_completion_tokens=baseline_completion or None,
        candidate_completion_tokens=candidate_completion or None,
        evaluator_json=json.dumps(evaluator, sort_keys=True),
        fixture_hash=fixture_hash,
        created_at=utcnow_iso(),
        note=note,
    )
    source_store.save_evaluation_run(run)
    return run
