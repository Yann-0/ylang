"""Archive helpers for unused or low-effectiveness prompt templates."""

from __future__ import annotations

from ylang.library.effectiveness import build_effectiveness_scores
from ylang.library.store import Library
from ylang.usage.improver_analytics import template_injection_counts
from ylang.usage.store import UsageStore, UsageWindow


def archive_template(library: Library, template_id: str) -> bool:
    """Archive one non-seed template (sets visibility to ``archived``)."""
    template = library.recall(template_id)
    if template is None or template.source == "seed":
        return False
    return library.set_visibility(template_id, "archived")


def unarchive_template(
    library: Library,
    template_id: str,
    *,
    visibility: str = "private",
) -> bool:
    """Restore an archived template to ``private`` or ``public``."""
    template = library.recall(template_id)
    if template is None or template.visibility != "archived":
        return False
    if visibility not in {"public", "private"}:
        msg = "unarchive visibility must be public or private"
        raise ValueError(msg)
    return library.set_visibility(template_id, visibility)  # type: ignore[arg-type]


def archive_unused_public_templates(
    library: Library,
    store: UsageStore,
    *,
    window: UsageWindow | None = None,
) -> list[str]:
    """Archive public non-seed templates that were never injected into improver context."""
    usage = template_injection_counts(store, window or UsageWindow.all_time())
    archived: list[str] = []
    for summary in library.list(visibility="public"):
        if summary.source == "seed":
            continue
        if usage.get(summary.template_id, 0) != 0:
            continue
        if archive_template(library, summary.template_id):
            archived.append(summary.template_id)
    return archived


def archive_low_effectiveness_templates(
    library: Library,
    store: UsageStore,
    *,
    window_days: int = 30,
    min_samples: int = 3,
    archive_learned_zero_accept: bool = True,
    archive_public_zero_accept: bool = True,
    archive_unused_public: bool = True,
) -> list[str]:
    """Archive templates matching hygiene rules; returns newly archived template ids."""
    archived: list[str] = []
    seen: set[str] = set()

    def _archive(template_id: str) -> None:
        if template_id in seen:
            return
        if archive_template(library, template_id):
            seen.add(template_id)
            archived.append(template_id)

    if archive_unused_public:
        for template_id in archive_unused_public_templates(library, store):
            seen.add(template_id)
            archived.append(template_id)

    effectiveness = build_effectiveness_scores(
        store,
        window_days=window_days,
        min_samples=min_samples,
    )
    zero_accept = {
        template_id
        for template_id, accept_rate in effectiveness.items()
        if accept_rate == 0.0
    }
    for template_id in zero_accept:
        template = library.recall(template_id)
        if template is None or template.visibility == "archived":
            continue
        if template.source == "learned" and archive_learned_zero_accept:
            _archive(template_id)
        elif template.source != "seed" and archive_public_zero_accept:
            if template.visibility == "public" or template.source == "user":
                _archive(template_id)

    return archived


def eligible_unused_public_template_ids(
    library: Library,
    usage_counts: dict[str, int],
) -> list[str]:
    """Return public non-seed template ids with zero improver injections."""
    return [
        summary.template_id
        for summary in library.list(visibility="public")
        if summary.source != "seed" and usage_counts.get(summary.template_id, 0) == 0
    ]


def eligible_zero_accept_template_ids(
    library: Library,
    store: UsageStore,
    *,
    window_days: int = 30,
    min_samples: int = 3,
) -> list[str]:
    """Return non-seed, non-archived template ids with 0% accept and enough samples."""
    effectiveness = build_effectiveness_scores(
        store,
        window_days=window_days,
        min_samples=min_samples,
    )
    toxic_ids: list[str] = []
    for template_id, accept_rate in effectiveness.items():
        if accept_rate != 0.0:
            continue
        template = library.recall(template_id)
        if template is None or template.source == "seed":
            continue
        if template.visibility == "archived":
            continue
        toxic_ids.append(template_id)
    return toxic_ids
