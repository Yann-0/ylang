"""AI-assisted template improvement for the admin console."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from ylang.library.types import TemplateParam

if TYPE_CHECKING:
    from ylang.core.engine import Engine

logger = logging.getLogger(__name__)

_IMPROVE_SYSTEM = """\
You improve Ylang prompt templates for clarity, structure, and reuse.
Respond with JSON only:
{
  "name": "short display name",
  "body": "template body using {param} placeholders",
  "params": [{"name": "param", "description": "what it means", "default": null or "value"}],
  "rationale": "one sentence on what changed"
}
Rules:
- Preserve the author's intent; do not invent unrelated tasks.
- Every {name} in body must appear in params.
- Prefer concise, actionable template wording.
"""

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def improve_template_with_ai(
    *,
    name: str,
    body: str,
    params: list[TemplateParam],
    engine: Engine,
    instruction: str = "",
) -> dict[str, Any]:
    """Return improved template fields from the LLM, or ``ok: false`` on failure."""
    payload = {
        "name": name,
        "body": body,
        "params": [
            {
                "name": param.name,
                "description": param.description,
                "default": param.default,
            }
            for param in params
        ],
        "instruction": instruction.strip() or "Improve clarity and structure.",
    }
    completion = engine.complete(
        [
            {"role": "system", "content": _IMPROVE_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        activity="reason",
        improver_fired=False,
    )
    if not completion.success:
        return {"ok": False, "error": completion.error or "LLM call failed"}
    parsed = _parse_improve_response(completion.content)
    if parsed is None:
        return {"ok": False, "error": "Could not parse LLM JSON response"}
    return {"ok": True, **parsed}


def _parse_improve_response(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    match = _JSON_BLOCK_RE.search(text)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    body = str(data.get("body", "")).strip()
    if not body:
        return None
    params_raw = data.get("params", [])
    params: list[dict[str, str | None]] = []
    if isinstance(params_raw, list):
        for item in params_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            default = item.get("default")
            params.append(
                {
                    "name": name,
                    "description": str(item.get("description", "")),
                    "default": str(default) if default is not None else None,
                }
            )
    return {
        "name": str(data.get("name", "")).strip(),
        "body": body,
        "params": params,
        "rationale": str(data.get("rationale", "")).strip(),
    }
