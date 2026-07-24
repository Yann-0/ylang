"""AI-assisted fact suggestions grounded in improver usage analytics."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from ylang.usage.improver_analytics import summarize_improver
from ylang.usage.store import UsageWindow

if TYPE_CHECKING:
    from ylang.core.engine import Engine
    from ylang.usage.store import UsageStore

logger = logging.getLogger(__name__)

_SUGGEST_SYSTEM = """\
You suggest short durable user facts for the Ylang improver memory store.
Facts are preferences the improver injects as context (stack choices, style rules,
project conventions). Respond with JSON only:
{
  "suggestions": [
    {
      "fact": "one concise preference sentence",
      "scope": "private" or "shareable",
      "workspace": "" or a short project tag,
      "rationale": "one sentence linking this fact to the evidence"
    }
  ]
}
Rules:
- Ground every suggestion in the provided analytics (rejections, samples, funnel).
- Prefer 3–6 concrete, actionable facts. Skip vague advice.
- Do not invent metrics or tools not supported by the evidence.
- Prefer scope "private" unless the preference is clearly shareable.
- Never write facts into storage; propose only.
"""

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")
_MAX_SAMPLES = 12
_MAX_SUGGESTIONS = 8


def suggest_facts_from_usage(
    store: UsageStore,
    engine: Engine,
    *,
    window: UsageWindow | None = None,
) -> dict[str, Any]:
    """Return proposed facts from usage analytics via a reason-model call.

    Propose-only: never writes to the memory store. Omits an explicit model so
    the Engine router resolves ``activity="reason"``.
    """
    active_window = window or UsageWindow.last_days(7)
    funnel = summarize_improver(store, active_window)
    samples = _recent_improver_samples(store, active_window)
    if funnel.total_fired < 1 and not samples and not funnel.top_rejection_reasons:
        return {
            "ok": False,
            "error": "Not enough improver usage to suggest facts yet.",
        }
    evidence = {
        "funnel": {
            "total_fired": funnel.total_fired,
            "accept_rate": round(funnel.accept_rate, 3),
            "validation_rate": round(funnel.validation_rate, 3),
            "top_rejections": funnel.top_rejection_reasons,
        },
        "recent_improver_samples": samples,
    }
    completion = engine.complete(
        [
            {"role": "system", "content": _SUGGEST_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(evidence, ensure_ascii=False),
            },
        ],
        activity="reason",
        improver_fired=False,
    )
    if not completion.success:
        logger.debug("fact suggest LLM failed: %s", completion.error)
        return {"ok": False, "error": completion.error or "LLM call failed"}
    suggestions = _parse_suggestions(completion.content)
    if not suggestions:
        return {"ok": False, "error": "Could not parse LLM JSON response"}
    return {"ok": True, "suggestions": suggestions}


def _recent_improver_samples(store: UsageStore, window: UsageWindow) -> list[str]:
    """Collect recent non-empty improver input samples (newest first, deduped)."""
    seen: set[str] = set()
    samples: list[str] = []
    for row in store.recall_usage(window):
        if not row.improver_fired:
            continue
        sample = (row.improver_input_sample or "").strip()
        if not sample:
            continue
        key = " ".join(sample.lower().split())
        if key in seen:
            continue
        seen.add(key)
        samples.append(sample)
        if len(samples) >= _MAX_SAMPLES:
            break
    return samples


def _parse_suggestions(raw: str) -> list[dict[str, str]]:
    text = raw.strip()
    match = _JSON_BLOCK_RE.search(text)
    if match is None:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    items: list[Any]
    if isinstance(data, dict):
        items = data.get("suggestions", [])
        if not isinstance(items, list):
            return []
    elif isinstance(data, list):
        items = data
    else:
        return []
    suggestions: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact", "")).strip()
        if not fact:
            continue
        scope = str(item.get("scope", "private")).strip().lower()
        if scope not in {"private", "shareable"}:
            scope = "private"
        suggestions.append(
            {
                "fact": fact,
                "scope": scope,
                "workspace": str(item.get("workspace", "")).strip(),
                "rationale": str(item.get("rationale", "")).strip(),
            }
        )
        if len(suggestions) >= _MAX_SUGGESTIONS:
            break
    return suggestions
