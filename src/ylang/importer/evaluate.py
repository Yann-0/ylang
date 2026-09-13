"""Candidate-vs-current evaluation using existing experiment/outcome stores."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ylang.importer.normalize import content_hash, sha256_text
from ylang.importer.source_store import PromptSourceStore
from ylang.importer.source_types import SourceItem
from ylang.library.store import Library
from ylang.usage.experiments import ExperimentStore, ExperimentVariant
from ylang.usage.improver_analytics import template_effectiveness
from ylang.usage.store import UsageWindow

if TYPE_CHECKING:
    from ylang.usage.store import UsageStore

MIN_OUTCOME_SAMPLES = 3

OutcomeStatus = Literal["improved", "regressed", "unchanged", "pending"]


@dataclass(frozen=True, slots=True)
class TemplateOutcomeSnapshot:
    """Measured local outcomes for one template. Missing stats stay None."""

    template_id: str
    version: int | None
    accept_rate: float | None
    avg_cost: float | None
    avg_latency_ms: float | None
    injections: int


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Local comparison report. Does not call an LLM or shift retrieval traffic.

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


def measure_template(
    library: Library,
    usage_store: UsageStore | None,
    template_id: str,
) -> TemplateOutcomeSnapshot:
    """Snapshot accept/cost/latency for a local template from existing usage."""
    template = library.recall(template_id)
    version = template.version if template is not None else None
    empty = TemplateOutcomeSnapshot(
        template_id=template_id,
        version=version,
        accept_rate=None,
        avg_cost=None,
        avg_latency_ms=None,
        injections=0,
    )
    if usage_store is None:
        return empty
    rows = template_effectiveness(usage_store, UsageWindow.all_time(), min_samples=1)
    for row in rows:
        if row.template_id == template_id:
            return TemplateOutcomeSnapshot(
                template_id=template_id,
                version=version,
                accept_rate=row.accept_rate,
                avg_cost=row.avg_cost,
                avg_latency_ms=row.avg_latency_ms,
                injections=row.injections,
            )
    return empty


def body_diff_ratio(current_body: str, candidate_body: str) -> float:
    """Return 0.0 when bodies match and 1.0 when they share no overlap."""
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
) -> tuple[OutcomeStatus, float | None]:
    """Classify whether promoted usage improved versus the captured baseline."""
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
    """Compare a candidate to the current local template without live A/B traffic.

    Untrusted candidate text is never injected into improver retrieval. Optional
    ``fixture_input`` is operator-supplied, stored locally, and never sent to a
    newly configured provider.
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
        measure_template(library, usage_store, current_id) if current_id else None
    )
    current_body = ""
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
    diff = body_diff_ratio(current_body, item.body) if current_id else None
    fixture_hash: str | None = None
    fixture_chars: int | None = None
    if fixture_input:
        fixture_hash = sha256_text(fixture_input)
        fixture_chars = len(fixture_input)
    note = (
        "Local comparison only. Experiment traffic stays at 0% so untrusted "
        "candidates are not injected into retrieval. Private history is not sent "
        "to a new provider. Do not infer quality from model completion without an "
        "explicit operator outcome."
    )
    report = CandidateEvaluation(
        experiment_id=experiment_id,
        candidate_variant=candidate_variant,
        current_variant=current_variant,
        current_template_id=current_id,
        current_template_version=snapshot.version if snapshot else None,
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
    return report
