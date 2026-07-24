"""Parse improver LLM JSON / prose payloads into improved text and changes."""

from __future__ import annotations

import json
import logging
import re

from ylang.improver.types import Change

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)

_ALLOWED_KINDS: frozenset[str] = frozenset(
    {"clarity", "format", "constraint", "example", "scope"}
)

def _parse_model_output(raw: str) -> tuple[str, list[Change]]:
    data = _loads_improver_payload(_extract_json_payload(raw))
    improved = str(data.get("improved", ""))
    changes: list[Change] = []
    for item in data.get("changes", []):
        kind = str(item.get("kind", ""))
        if kind not in _ALLOWED_KINDS:
            msg = f"invalid change kind: {kind}"
            raise ValueError(msg)
        changes.append(
            Change(
                kind=kind,  # type: ignore[arg-type]
                description=str(item.get("description", "")),
                before=str(item.get("before", "")),
                after=str(item.get("after", "")),
            )
        )
    return improved, changes


def _loads_improver_payload(payload: str) -> dict[str, object]:
    """Parse improver JSON, with a regex fallback for multiline model output."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = _extract_improver_fields(payload)
    if not isinstance(data, dict):
        msg = "model output must be a JSON object"
        raise ValueError(msg)
    return data


def _decode_improved_json_string(raw: str) -> str:
    """Unescape a JSON string value recovered from broken model output."""
    return raw.replace("\\n", "\n").replace('\\"', '"')


def _extract_changes_array(payload: str) -> tuple[list[object], int | None]:
    """Return (changes, match_start) from broken JSON; empty list when absent."""
    for pattern in (
        r'"changes"\s*:\s*(\[[\s\S]*?\])\s*,\s*"improved"\s*:',
        r'"changes"\s*:\s*(\[[\s\S]*?\])\s*\}',
        r'"changes"\s*:\s*(\[[\s\S]*\])\s*\}?\s*$',
    ):
        match = re.search(pattern, payload)
        if match is not None:
            return json.loads(match.group(1)), match.start()
    return [], None


def _extract_improved_from_payload(
    payload: str, *, before: str | None = None
) -> str | None:
    """Extract the improved string from a (possibly broken) JSON payload."""
    head = before if before is not None else payload
    improved_match = re.search(
        r'"improved"\s*:\s*"(.*?)"\s*,\s*"changes"\s*:',
        head,
        re.DOTALL,
    )
    if improved_match is not None:
        return _decode_improved_json_string(improved_match.group(1))
    improved_match = re.search(
        r'"changes"\s*:\s*\[[\s\S]*?\]\s*,\s*"improved"\s*:\s*"(.*?)"\s*\}?\s*$',
        payload,
        re.DOTALL,
    )
    if improved_match is not None:
        return _decode_improved_json_string(improved_match.group(1))
    loose = re.search(r'"improved"\s*:\s*"([\s\S]*)', head)
    if loose is None:
        return None
    improved_raw = loose.group(1)
    for sentinel in ('",\n  "changes"', '", "changes"', '",\n"changes"', '",'):
        if sentinel in improved_raw:
            improved_raw = improved_raw.split(sentinel, 1)[0]
            break
    improved_raw = improved_raw.rstrip('"')
    if not improved_raw:
        return None
    return _decode_improved_json_string(improved_raw)


def _extract_improver_fields(payload: str) -> dict[str, object]:
    """Recover improved/changes when json.loads fails on multiline strings."""
    changes, changes_start = _extract_changes_array(payload)
    head = payload[:changes_start] if changes_start is not None else payload
    improved = _extract_improved_from_payload(payload, before=head)
    if improved is None:
        msg = "could not locate improved field in model output"
        raise ValueError(msg)
    return {"improved": improved, "changes": changes}


def _try_parse_plain_spec(raw: str) -> str | None:
    """Return markdown spec text when the model skipped JSON entirely."""
    text = _extract_json_payload(raw).strip()
    if text.startswith("{") or text.startswith("["):
        return None
    if text.startswith("## ") or "\n## " in text:
        from ylang.improver.validate import _has_structured_expansion

        if _has_structured_expansion(text):
            return text
    return None


def _is_model_prose_response(raw: str) -> bool:
    """Return True when the model replied in plain prose instead of JSON or a spec."""
    text = _extract_json_payload(raw).strip()
    if not text:
        return False
    if text.startswith("{") or text.startswith("["):
        return False
    if text.startswith("## ") or "\n## " in text:
        return False
    return True


def _extract_json_payload(raw: str) -> str:
    """Strip markdown fences and whitespace so json.loads can parse model output."""
    text = raw.strip()
    if not text:
        msg = "model returned empty content"
        raise ValueError(msg)
    match = _JSON_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text

