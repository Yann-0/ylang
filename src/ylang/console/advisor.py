"""AI config advisor for the admin console."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ylang.console.proposals import PendingProposal, pending_proposal_from_setting
from ylang.core.runtime_settings import HOT_RELOADABLE_KEYS
from ylang.usage.improver_analytics import summarize_improver, template_effectiveness
from ylang.usage.optimizer import generate_optimization_suggestions, serialize_suggestion
from ylang.usage.store import UsageWindow

if TYPE_CHECKING:
    from ylang.core.engine import Engine
    from ylang.core.runtime_settings import RuntimeSettingsStore
    from ylang.settings import Settings
    from ylang.usage.store import UsageStore

logger = logging.getLogger(__name__)

_ADVISOR_SYSTEM = """\
You are the Ylang admin assistant. Answer using the provided analytics JSON.
Suggest concrete setting changes (key + value) when appropriate.
Respond in plain text with short sections: Summary, Recommendations, Next steps.
Never invent metrics not present in the data.

After the plain-text reply, append a single JSON object on its own line in this exact form
(use an empty list when you recommend no setting changes):
{"setting_changes":[{"key":"<hot_reloadable_key>","value":"<value>","rationale":"<short>"}]}
Only use keys from applyable_setting_keys. Values must be concrete (e.g. "true", "3").
"""

_SETTING_JSON_RE = re.compile(
    r"\{[^{}]*\"setting_changes\"\s*:\s*\[[^\]]*\][^{}]*\}",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class AdvisorReply:
    """Advisor text plus optional applyable setting proposals."""

    text: str
    setting_proposals: list[PendingProposal]


def generate_advisor_reply(
    question: str,
    *,
    store: UsageStore,
    engine: Engine,
    settings: Settings,
    runtime_store: RuntimeSettingsStore,
) -> AdvisorReply:
    """Return an LLM-generated admin advisory reply grounded in live analytics.

    Uses ``activity="reason"`` without a forced model so the reason activity list
    (including ``models_reason`` runtime overrides) selects the model.
    """
    window = UsageWindow.last_days(7)
    funnel = summarize_improver(store, window)
    templates = template_effectiveness(store, window)[:8]
    suggestions = generate_optimization_suggestions(store, window)[:6]
    applyable_keys = sorted(HOT_RELOADABLE_KEYS - {"usage_digest_last_at"})
    context = {
        "question": question.strip(),
        "funnel": {
            "accept_rate": round(funnel.accept_rate, 3),
            "validation_rate": round(funnel.validation_rate, 3),
            "total_fired": funnel.total_fired,
            "top_rejections": funnel.top_rejection_reasons,
        },
        "templates": [
            {
                "template_id": row.template_id,
                "accept_rate": round(row.accept_rate, 3),
                "injections": row.injections,
            }
            for row in templates
        ],
        "suggestions": [serialize_suggestion(item) for item in suggestions],
        "runtime_overrides": runtime_store.as_dict(),
        "daily_budget_usd": settings.daily_budget_usd,
        "fallback_model": settings.fallback_model,
        "applyable_setting_keys": applyable_keys,
    }
    completion = engine.complete(
        [
            {"role": "system", "content": _ADVISOR_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(context, ensure_ascii=False),
            },
        ],
        activity="reason",
        improver_fired=False,
    )
    if not completion.success:
        logger.debug("advisor LLM failed: %s", completion.error)
        return AdvisorReply(
            text=(
                "Could not reach the LLM for an advisory reply. "
                f"Error: {completion.error or 'unknown'}"
            ),
            setting_proposals=[],
        )
    raw = completion.content.strip()
    text, proposals = _parse_advisor_content(raw)
    return AdvisorReply(
        text=text or "No advisory reply generated.",
        setting_proposals=proposals,
    )


def _parse_advisor_content(raw: str) -> tuple[str, list[PendingProposal]]:
    """Split plain-text reply from trailing setting_changes JSON."""
    match = _SETTING_JSON_RE.search(raw)
    if match is None:
        return raw, []
    text = (raw[: match.start()] + raw[match.end() :]).strip()
    proposals: list[PendingProposal] = []
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return text or raw, []
    changes = payload.get("setting_changes")
    if not isinstance(changes, list):
        return text or raw, []
    seen: set[str] = set()
    for item in changes:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        rationale = str(item.get("rationale", "")).strip()
        proposal = pending_proposal_from_setting(
            key=key, value=value, rationale=rationale
        )
        if proposal is None or proposal.proposal_id in seen:
            continue
        seen.add(proposal.proposal_id)
        proposals.append(proposal)
    return text or raw, proposals
