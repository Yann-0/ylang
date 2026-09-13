"""Prompt intelligence types: sources, candidates, and refresh summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

POLICY_VERSION = "2026-09-12"
ADAPTER_VERSION = "1"

MANUAL_SOURCE_ID = "manual-import"

SourceAdapterName = Literal[
    "prompts-chat",
    "github-awesome-copilot",
    "fabric-patterns",
    "csv-manual",
]
SourceTrustTier = Literal[
    "community-broad",
    "curated-coding",
    "curated-patterns",
    "manual",
]
CandidateState = Literal[
    "candidate_new",
    "candidate_changed",
    "reviewed",
    "promoted",
    "rejected",
    "removed_upstream",
    "quarantined",
]
RiskLevel = Literal["low", "review", "high"]
TaskFamily = Literal[
    "code",
    "debugging",
    "architecture",
    "research",
    "summarization",
    "extraction",
    "transformation",
    "writing",
    "planning",
    "reasoning",
    "evaluation",
    "data-analysis",
    "agent-orchestration",
    "other",
]
RefreshStatus = Literal["success", "unchanged", "error", "blocked"]

ACTIVE_CANDIDATE_STATES: frozenset[str] = frozenset(
    {
        "candidate_new",
        "candidate_changed",
        "reviewed",
        "quarantined",
    }
)
REVIEW_QUEUE_STATES: frozenset[str] = frozenset(
    {
        "candidate_new",
        "candidate_changed",
        "quarantined",
        "reviewed",
    }
)


@dataclass(frozen=True, slots=True)
class PromptSource:
    """Allowlisted public or manual prompt source record."""

    source_id: str
    name: str
    adapter: SourceAdapterName
    canonical_url: str
    repo_url: str | None
    license_spdx: str
    license_url: str | None
    trust_tier: SourceTrustTier
    enabled: bool
    refresh_interval_hours: int
    last_attempt_at: str | None
    last_success_at: str | None
    last_revision: str | None
    last_etag: str | None
    last_error: str | None
    policy_version: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SourceItem:
    """One upstream prompt item in candidate quarantine."""

    item_id: str
    source_id: str
    upstream_item_id: str
    canonical_url: str | None
    source_revision: str | None
    content_hash: str
    normalized_fingerprint: str
    title: str
    body: str
    params_json: str
    metadata_json: str
    first_seen_at: str
    last_seen_at: str
    candidate_state: CandidateState
    risk_level: RiskLevel
    risk_reasons: tuple[str, ...]
    quality_score: int
    quality_reasons: tuple[str, ...]
    task_family: TaskFamily
    model_hint: str | None
    duplicate_of_item_id: str | None
    duplicate_template_id: str | None
    linked_template_id: str | None
    linked_template_version: int | None
    license_spdx: str | None
    adapter_version: str
    previous_body: str | None
    previous_content_hash: str | None


@dataclass(frozen=True, slots=True)
class ParsedUpstreamItem:
    """Adapter output before persistence."""

    upstream_item_id: str
    title: str
    body: str
    canonical_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    model_hint: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RefreshSummary:
    """Local summary of one source refresh."""

    source_id: str
    status: RefreshStatus
    revision_before: str | None
    revision_after: str | None
    new: int = 0
    changed: int = 0
    removed: int = 0
    duplicates: int = 0
    quarantined: int = 0
    rejected_suppressed: int = 0
    errors: int = 0
    error: str | None = None
    unchanged: int = 0

    @property
    def imported(self) -> int:
        """Compatibility alias used by MCP ``import_public_prompts``."""
        return self.new

    @property
    def skipped(self) -> int:
        """Compatibility alias: unchanged plus suppressed rejected hashes."""
        return self.unchanged + self.rejected_suppressed


@dataclass(frozen=True, slots=True)
class PromotionBaseline:
    """Outcome snapshot captured at promote time for later deltas."""

    template_id: str
    version: int
    item_id: str
    accept_rate: float | None
    avg_cost: float | None
    avg_latency_ms: float | None
    injections: int
    captured_at: str


@dataclass(frozen=True, slots=True)
class TemplateProvenance:
    """Durable link from a promoted template version to an upstream item."""

    template_id: str
    version: int
    item_id: str
    source_id: str
    upstream_revision: str | None
    content_hash: str
    canonical_url: str | None
    promoted_at: str


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Explainable static quality triage (not measured effectiveness)."""

    score: int
    reasons: tuple[str, ...]
    task_family: TaskFamily


@dataclass(frozen=True, slots=True)
class RiskReport:
    """Explainable static risk triage. Never a safety proof."""

    level: RiskLevel
    reasons: tuple[str, ...]


def utcnow_iso(now: datetime | None = None) -> str:
    """Return an ISO-8601 UTC timestamp."""
    from datetime import timezone

    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
