"""Governed apply proposals from optimizer suggestions and experiment winners."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from urllib.parse import unquote

from ylang.console.apply_audit import ApplyAuditStore
from ylang.core.runtime_settings import HOT_RELOADABLE_KEYS, RuntimeSettingsStore
from ylang.library.hygiene import archive_template, eligible_zero_accept_template_ids
from ylang.library.pattern_detector import (
    UsagePatternDetector,
    propose_template_from_pattern,
)
from ylang.library.store import Library, save_learned_template
from ylang.usage.experiment_results import VariantOutcome, summarize_experiment_outcomes
from ylang.usage.experiments import ExperimentStore
from ylang.usage.optimizer import (
    APPLY_ARCHIVE_TEMPLATES,
    APPLY_LEARNED_TEMPLATE,
    APPLY_RUNTIME_SETTING,
    OptimizationSuggestion,
    generate_optimization_suggestions,
)
from ylang.usage.improver_analytics import template_injection_counts
from ylang.usage.store import UsageStore, UsageWindow

APPLY_SUGGEST_FACTS = "suggest_facts"

# Writable via governed apply (excludes digests bookkeeping stamp).
_APPLYABLE_SETTING_KEYS: frozenset[str] = HOT_RELOADABLE_KEYS - {"usage_digest_last_at"}


@dataclass(frozen=True, slots=True)
class PendingProposal:
    """One optimization or experiment proposal awaiting explicit user apply."""

    proposal_id: str
    kind: str
    title: str
    description: str
    evidence: str
    priority: str
    apply_type: str
    setting_key: str | None = None
    setting_value: str | None = None
    template_id: str | None = None


def collect_pending_proposals(
    store: UsageStore,
    connection: sqlite3.Connection,
    window: UsageWindow,
) -> list[PendingProposal]:
    """Return applyable proposals from optimizer suggestions and experiment winners.

    Already-applied proposals (audit log) and runtime settings that already match
    the suggested value are excluded so they do not reappear after Apply.
    """
    proposals: list[PendingProposal] = []
    runtime_overrides = RuntimeSettingsStore(connection).as_dict()
    suggestions = generate_optimization_suggestions(
        store,
        window,
        runtime_overrides=runtime_overrides,
    )
    for item in suggestions:
        apply_type = _suggestion_apply_type(item)
        if apply_type is None:
            continue
        proposals.append(
            PendingProposal(
                proposal_id=f"suggestion:{item.suggestion_id}",
                kind=item.kind,
                title=item.title,
                description=item.description,
                evidence=item.evidence,
                priority=item.priority,
                apply_type=apply_type,
                setting_key=item.setting_key,
                setting_value=item.setting_value,
                template_id=item.template_id,
            )
        )

    outcomes = summarize_experiment_outcomes(store, window)
    for winner in _experiment_winners(connection, outcomes):
        proposals.append(
            PendingProposal(
                proposal_id=f"experiment:{winner['experiment_id']}:{winner['variant_id']}",
                kind="experiment_winner",
                title=f"Promote experiment variant '{winner['variant_id']}'",
                description=(
                    f"Activate variant with {winner['accept_rate']:.0%} accept rate "
                    f"over {winner['samples']} samples."
                ),
                evidence=(
                    f"Experiment {winner['experiment_id']}; config {winner['config_hash']}."
                ),
                priority="high",
                apply_type="experiment_activate",
            )
        )
    return filter_already_applied(proposals, connection)


def collect_control_proposals(
    store: UsageStore,
    library: Library,
    connection: sqlite3.Connection,
    window: UsageWindow,
) -> list[PendingProposal]:
    """Return Control Center one-click proposals (facts, archive, tuning presets)."""
    proposals: list[PendingProposal] = []

    proposals.append(
        PendingProposal(
            proposal_id="action:suggest-facts",
            kind="facts",
            title="Suggest facts from improver usage",
            description=(
                "Run the fact suggester on recent improver analytics and open the "
                "Facts page to review candidates (nothing saved until you confirm)."
            ),
            evidence="Control Center AI ops — governed apply records initiation.",
            priority="medium",
            apply_type=APPLY_SUGGEST_FACTS,
        )
    )

    usage_counts = template_injection_counts(store, UsageWindow.all_time())
    unused_public = [
        summary.template_id
        for summary in library.list(visibility="public")
        if summary.source != "seed" and usage_counts.get(summary.template_id, 0) == 0
    ]
    if unused_public:
        encoded = ",".join(unused_public[:25])
        proposals.append(
            PendingProposal(
                proposal_id=f"action:archive-unused:{encoded}",
                kind="template_hygiene",
                title=f"Archive {len(unused_public)} unused public template(s)",
                description=(
                    "Set visibility to archived for public imports with zero improver "
                    "injections (seed templates excluded)."
                ),
                evidence=f"Unused ids: {', '.join(unused_public[:8])}"
                + ("…" if len(unused_public) > 8 else ""),
                priority="medium",
                apply_type=APPLY_ARCHIVE_TEMPLATES,
                template_id=encoded,
            )
        )

    toxic_ids = eligible_zero_accept_template_ids(library, store)
    if toxic_ids:
        encoded_toxic = ",".join(toxic_ids[:25])
        proposals.append(
            PendingProposal(
                proposal_id=f"action:archive-toxic:{encoded_toxic}",
                kind="template_hygiene",
                title=f"Quarantine {len(toxic_ids)} toxic template(s) (0% accept)",
                description=(
                    "Archive non-seed templates with 0% accept rate and enough samples "
                    "(last 30 days)."
                ),
                evidence=f"Toxic ids: {', '.join(toxic_ids[:8])}"
                + ("…" if len(toxic_ids) > 8 else ""),
                priority="high",
                apply_type=APPLY_ARCHIVE_TEMPLATES,
                template_id=encoded_toxic,
            )
        )

    tuning: list[tuple[str, str, str]] = [
        (
            "improver_timeout_sec",
            "18",
            "Raise improver wall-clock budget (pair with YLANG_HOOK_TIMEOUT_SEC≥20).",
        ),
        (
            "learned_template_limit",
            "1",
            "Trim learned templates in improver context for latency and less noise.",
        ),
        (
            "improver_critique",
            "false",
            "Disable second-pass critique on the fast/cheap improver path.",
        ),
    ]
    for key, value, rationale in tuning:
        item = pending_proposal_from_setting(key=key, value=value, rationale=rationale)
        if item is not None:
            proposals.append(item)

    fast = pending_proposal_from_setting(
        key="models_improve",
        value="mistral/mistral-small-latest,anthropic/claude-haiku-4-5",
        rationale="Fast/cheap improver routing preset.",
    )
    if fast is not None:
        proposals.append(
            PendingProposal(
                proposal_id=fast.proposal_id,
                kind="control_preset",
                title="Fast/cheap improver models",
                description=fast.description,
                evidence="Control Center preset — mistral-small + claude-haiku-4-5.",
                priority="low",
                apply_type=APPLY_RUNTIME_SETTING,
                setting_key=fast.setting_key,
                setting_value=fast.setting_value,
            )
        )

    return filter_already_applied(proposals, connection)


def proposal_redirect_after_apply(proposal_id: str) -> str | None:
    """Optional post-apply redirect path for action proposals."""
    if proposal_id == "action:suggest-facts":
        return "/console/facts?suggest=1"
    return None


def filter_already_applied(
    proposals: list[PendingProposal],
    connection: sqlite3.Connection,
) -> list[PendingProposal]:
    """Drop proposals that were applied or whose setting is already in effect."""
    applied = ApplyAuditStore(connection).applied_proposal_ids()
    runtime = RuntimeSettingsStore(connection)
    remaining: list[PendingProposal] = []
    for item in proposals:
        if item.proposal_id in applied:
            continue
        if (
            item.apply_type == APPLY_RUNTIME_SETTING
            and item.setting_key
            and item.setting_value is not None
        ):
            current = runtime.get(item.setting_key)
            if (
                current is not None
                and current.strip().lower() == item.setting_value.strip().lower()
            ):
                continue
        remaining.append(item)
    return remaining


def pending_proposal_from_setting(
    *,
    key: str,
    value: str,
    rationale: str = "",
) -> PendingProposal | None:
    """Build an applyable setting proposal (e.g. from Advisor recommendations)."""
    if key not in _APPLYABLE_SETTING_KEYS:
        return None
    value = value.strip()
    if not value:
        return None
    return PendingProposal(
        proposal_id=encode_setting_proposal_id(key, value),
        kind="advisor_setting",
        title=f"Set {key}={value}",
        description=rationale or f"Apply runtime setting {key}={value}.",
        evidence="Recommended by Advisor from live analytics.",
        priority="medium",
        apply_type=APPLY_RUNTIME_SETTING,
        setting_key=key,
        setting_value=value,
    )


def encode_setting_proposal_id(key: str, value: str) -> str:
    """Encode a direct setting apply id as ``setting:key=value``."""
    return f"setting:{key}={value}"


def parse_setting_proposal_id(proposal_id: str) -> tuple[str, str] | None:
    """Parse ``setting:key=value`` proposal ids."""
    if not proposal_id.startswith("setting:"):
        return None
    raw = proposal_id.removeprefix("setting:")
    if "=" not in raw:
        return None
    key, value = raw.split("=", 1)
    key = unquote(key.strip())
    value = unquote(value.strip())
    if key not in _APPLYABLE_SETTING_KEYS or not value:
        return None
    return key, value


def apply_proposal(
    proposal_id: str,
    *,
    store: UsageStore,
    library: Library,
    connection: sqlite3.Connection,
    runtime_store: RuntimeSettingsStore,
    audit_store: ApplyAuditStore,
    window: UsageWindow,
    actor: str = "console",
) -> str:
    """Apply one pending proposal after explicit user confirmation."""
    if proposal_id.startswith("suggestion:"):
        suggestion_id = proposal_id.removeprefix("suggestion:")
        return _apply_suggestion(
            suggestion_id,
            store=store,
            library=library,
            connection=connection,
            runtime_store=runtime_store,
            audit_store=audit_store,
            window=window,
            actor=actor,
        )
    if proposal_id.startswith("setting:"):
        parsed = parse_setting_proposal_id(proposal_id)
        if parsed is None:
            msg = f"invalid or disallowed setting proposal: {proposal_id}"
            raise ValueError(msg)
        key, value = parsed
        return _apply_runtime_setting(
            key,
            value,
            runtime_store=runtime_store,
            audit_store=audit_store,
            actor=actor,
            proposal_id=proposal_id,
        )
    if proposal_id.startswith("experiment:"):
        parts = proposal_id.removeprefix("experiment:").split(":", 1)
        if len(parts) != 2:
            msg = "invalid experiment proposal id"
            raise ValueError(msg)
        experiment_id, variant_id = parts
        return _apply_experiment_winner(
            experiment_id,
            variant_id,
            connection=connection,
            audit_store=audit_store,
            actor=actor,
            proposal_id=proposal_id,
        )
    if proposal_id == "action:suggest-facts":
        return _apply_suggest_facts(
            audit_store=audit_store,
            actor=actor,
            proposal_id=proposal_id,
        )
    if proposal_id.startswith("action:archive-unused:"):
        encoded = proposal_id.removeprefix("action:archive-unused:")
        return _apply_archive_templates(
            encoded,
            library=library,
            audit_store=audit_store,
            actor=actor,
            proposal_id=proposal_id,
        )
    if proposal_id.startswith("action:archive-toxic:"):
        encoded = proposal_id.removeprefix("action:archive-toxic:")
        return _apply_archive_templates(
            encoded,
            library=library,
            audit_store=audit_store,
            actor=actor,
            proposal_id=proposal_id,
        )
    msg = f"unknown proposal id: {proposal_id}"
    raise ValueError(msg)


def _suggestion_apply_type(suggestion: OptimizationSuggestion) -> str | None:
    if suggestion.apply_action == APPLY_LEARNED_TEMPLATE and suggestion.template_id:
        return APPLY_LEARNED_TEMPLATE
    if suggestion.apply_action == APPLY_ARCHIVE_TEMPLATES and suggestion.template_id:
        return APPLY_ARCHIVE_TEMPLATES
    if (
        suggestion.apply_action == APPLY_RUNTIME_SETTING
        and suggestion.setting_key
        and suggestion.setting_value
        and suggestion.setting_key in _APPLYABLE_SETTING_KEYS
    ):
        return APPLY_RUNTIME_SETTING
    return None


def _apply_runtime_setting(
    key: str,
    value: str,
    *,
    runtime_store: RuntimeSettingsStore,
    audit_store: ApplyAuditStore,
    actor: str,
    proposal_id: str,
) -> str:
    if key not in _APPLYABLE_SETTING_KEYS:
        msg = f"setting not applyable: {key}"
        raise ValueError(msg)
    runtime_store.set(key, value)
    detail = f"set runtime setting {key}={value}"
    audit_store.record(
        actor=actor,
        proposal_id=proposal_id,
        action_type=APPLY_RUNTIME_SETTING,
        detail=detail,
    )
    return detail


def _apply_suggestion(
    suggestion_id: str,
    *,
    store: UsageStore,
    library: Library,
    connection: sqlite3.Connection,
    runtime_store: RuntimeSettingsStore,
    audit_store: ApplyAuditStore,
    window: UsageWindow,
    actor: str,
) -> str:
    suggestions = generate_optimization_suggestions(store, window)
    match = next((item for item in suggestions if item.suggestion_id == suggestion_id), None)
    if match is None:
        msg = f"suggestion no longer available: {suggestion_id}"
        raise ValueError(msg)
    apply_type = _suggestion_apply_type(match)
    if apply_type == APPLY_LEARNED_TEMPLATE:
        pattern_id = suggestion_id.removeprefix("pattern-")
        detector = UsagePatternDetector(store)
        days = max(1, int((window.until - window.since).total_seconds() // 86400))
        patterns = detector.detect(window_days=days)
        pattern = next((item for item in patterns if item.pattern_id == pattern_id), None)
        if pattern is None:
            msg = f"pattern not found: {pattern_id}"
            raise ValueError(msg)
        proposal = propose_template_from_pattern(pattern)
        if proposal is None:
            msg = "no template proposal for pattern"
            raise ValueError(msg)
        save_learned_template(
            library,
            proposal.suggested_template_id,
            name=proposal.name,
            body=proposal.body,
            params=proposal.params,
        )
        detail = f"saved learned template {proposal.suggested_template_id}"
        audit_store.record(
            actor=actor,
            proposal_id=f"suggestion:{suggestion_id}",
            action_type=APPLY_LEARNED_TEMPLATE,
            detail=detail,
        )
        return detail
    if apply_type == APPLY_RUNTIME_SETTING:
        assert match.setting_key is not None
        assert match.setting_value is not None
        return _apply_runtime_setting(
            match.setting_key,
            match.setting_value,
            runtime_store=runtime_store,
            audit_store=audit_store,
            actor=actor,
            proposal_id=f"suggestion:{suggestion_id}",
        )
    if apply_type == APPLY_ARCHIVE_TEMPLATES:
        assert match.template_id is not None
        return _apply_archive_templates(
            match.template_id,
            library=library,
            audit_store=audit_store,
            actor=actor,
            proposal_id=f"suggestion:{suggestion_id}",
        )
    msg = f"suggestion is not applyable: {suggestion_id}"
    raise ValueError(msg)


def _apply_suggest_facts(
    *,
    audit_store: ApplyAuditStore,
    actor: str,
    proposal_id: str,
) -> str:
    detail = "initiated fact suggestion flow — review on Facts page"
    audit_store.record(
        actor=actor,
        proposal_id=proposal_id,
        action_type=APPLY_SUGGEST_FACTS,
        detail=detail,
    )
    return detail


def _apply_archive_templates(
    encoded_ids: str,
    *,
    library: Library,
    audit_store: ApplyAuditStore,
    actor: str,
    proposal_id: str,
) -> str:
    archived: list[str] = []
    for template_id in encoded_ids.split(","):
        tid = template_id.strip()
        if not tid:
            continue
        if archive_template(library, tid):
            archived.append(tid)
    if not archived:
        msg = "no templates archived (already archived or seed)"
        raise ValueError(msg)
    detail = f"archived {len(archived)} template(s): {', '.join(archived[:5])}"
    if len(archived) > 5:
        detail += "…"
    audit_store.record(
        actor=actor,
        proposal_id=proposal_id,
        action_type=APPLY_ARCHIVE_TEMPLATES,
        detail=detail,
    )
    return detail


def _apply_experiment_winner(
    experiment_id: str,
    variant_id: str,
    *,
    connection: sqlite3.Connection,
    audit_store: ApplyAuditStore,
    actor: str,
    proposal_id: str,
) -> str:
    store = ExperimentStore(connection)
    variants = [item for item in store.list_all() if item.experiment_id == experiment_id]
    if not any(item.variant_id == variant_id for item in variants):
        msg = f"variant not found: {variant_id}"
        raise ValueError(msg)
    for item in variants:
        store.set_active(
            experiment_id=item.experiment_id,
            variant_id=item.variant_id,
            active=item.variant_id == variant_id,
        )
    detail = f"activated {experiment_id}/{variant_id}"
    audit_store.record(
        actor=actor,
        proposal_id=proposal_id,
        action_type="experiment_activate",
        detail=detail,
    )
    return detail


def _experiment_winners(
    connection: sqlite3.Connection,
    outcomes: list[VariantOutcome],
) -> list[dict[str, object]]:
    """Return leading variants per experiment when samples are sufficient."""
    variant_experiments: dict[str, str] = {}
    cursor = connection.execute(
        "SELECT experiment_id, variant_id FROM prompt_experiments"
    )
    for experiment_id, variant_id in cursor.fetchall():
        variant_experiments[str(variant_id)] = str(experiment_id)

    by_experiment: dict[str, list[VariantOutcome]] = {}
    for outcome in outcomes:
        experiment_id = variant_experiments.get(outcome.variant_id)
        if experiment_id is None:
            continue
        by_experiment.setdefault(experiment_id, []).append(outcome)

    winners: list[dict[str, object]] = []
    for experiment_id, group in by_experiment.items():
        eligible = [item for item in group if item.samples >= 5]
        if len(eligible) < 2:
            continue
        leader = max(eligible, key=lambda item: item.accept_rate)
        trailing = [item for item in eligible if item.variant_id != leader.variant_id]
        if not trailing:
            continue
        if all(leader.accept_rate > item.accept_rate for item in trailing):
            winners.append(
                {
                    "experiment_id": experiment_id,
                    "variant_id": leader.variant_id,
                    "config_hash": leader.config_hash,
                    "samples": leader.samples,
                    "accept_rate": leader.accept_rate,
                }
            )
    return winners
