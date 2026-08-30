"""Trace capture levels and privacy policy for usage persistence."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

CaptureLevel = Literal["off", "minimal", "redacted", "full_local"]

DEFAULT_CAPTURE_LEVEL: CaptureLevel = "minimal"
CAPTURE_LEVELS: frozenset[str] = frozenset(
    {"off", "minimal", "redacted", "full_local"}
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._\-+=/]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key\s*[:=]\s*)\S+"),
)

_REDACTED_BODY_MAX = 500
_FULL_BODY_MAX = 4000
_ERROR_MAX = 240


def parse_capture_level(raw: str | None, *, default: CaptureLevel = DEFAULT_CAPTURE_LEVEL) -> CaptureLevel:
    """Parse a capture level string; unknown values fall back to ``default``."""
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in CAPTURE_LEVELS:
        return normalized  # type: ignore[return-value]
    return default


def hash_prompt_text(text: str) -> str:
    """Return a SHA-256 hex digest of normalized prompt text."""
    normalized = "\n".join(line.rstrip() for line in text.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_messages(messages: list[dict[str, Any]] | list[Any]) -> str | None:
    """Hash user/system message contents for correlation without storing bodies."""
    parts: list[str] = []
    for message in messages:
        if isinstance(message, dict):
            role = str(message.get("role") or "")
            content = message.get("content")
        else:
            role = str(getattr(message, "role", "") or "")
            content = getattr(message, "content", None)
        if role not in {"user", "system"}:
            continue
        if isinstance(content, str) and content.strip():
            parts.append(content)
    if not parts:
        return None
    return hash_prompt_text("\n".join(parts))


def redact_secrets(text: str) -> str:
    """Mask common secret shapes in free text."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.lower().startswith(r"(?i)\b(bearer"):
            redacted = pattern.sub(r"\1***", redacted)
        elif "api" in pattern.pattern.lower():
            redacted = pattern.sub(r"\1***", redacted)
        else:
            redacted = pattern.sub("***", redacted)
    return redacted


def truncate_text(text: str, max_len: int) -> str:
    """Truncate ``text`` to ``max_len``, appending ellipsis when needed."""
    stripped = text.strip()
    if len(stripped) <= max_len:
        return stripped
    if max_len <= 3:
        return stripped[:max_len]
    return stripped[: max_len - 3] + "..."


def redact_error_message(error: str | None) -> str | None:
    """Return a short, secret-scrubbed error string for persistence."""
    if error is None:
        return None
    cleaned = redact_secrets(error).strip()
    if not cleaned:
        return None
    return truncate_text(cleaned, _ERROR_MAX)


def classify_error(exc: BaseException | None, *, success: bool) -> str | None:
    """Map an exception (or failure without exc) to a stable error class."""
    if success:
        return None
    if exc is None:
        return "error"
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if status == 429 or "RateLimit" in name:
        return "rate_limit"
    if status in {500, 502, 503, 504} or any(
        token in name for token in ("ServiceUnavailable", "BadGateway", "InternalServer")
    ):
        return "provider_unavailable"
    if "Timeout" in name or "timeout" in str(exc).lower():
        return "timeout"
    if "NotFound" in name:
        return "not_found"
    if "BadRequest" in name:
        return "bad_request"
    return "error"


def tool_calls_for_capture(
    tool_calls: list[dict[str, Any]] | None,
    capture_level: CaptureLevel,
) -> str | None:
    """Serialize observable tool calls according to capture policy."""
    if capture_level == "off" or not tool_calls:
        return None
    safe: list[dict[str, Any]] = []
    for item in tool_calls:
        function = item.get("function") if isinstance(item, dict) else None
        name = ""
        if isinstance(function, dict):
            name = str(function.get("name") or "")
        entry: dict[str, Any] = {
            "id": item.get("id") if isinstance(item, dict) else None,
            "name": name or None,
        }
        if capture_level in {"redacted", "full_local"} and isinstance(function, dict):
            args = function.get("arguments")
            if isinstance(args, str) and args:
                max_len = _FULL_BODY_MAX if capture_level == "full_local" else _REDACTED_BODY_MAX
                entry["arguments"] = truncate_text(redact_secrets(args), max_len)
        safe.append(entry)
    return json.dumps(safe, separators=(",", ":"))


def prompt_body_for_capture(
    sample: str | None,
    capture_level: CaptureLevel,
) -> tuple[str | None, str | None]:
    """Return ``(improver_input_sample, prompt_body_redacted)`` for the level.

    ``off`` drops bodies. ``minimal`` keeps legacy truncated improver sample only
    when already provided by callers (improver path). ``redacted`` /
    ``full_local`` also set ``prompt_body_redacted``.
    """
    if sample is None or capture_level == "off":
        return None, None
    scrubbed = redact_secrets(sample)
    if capture_level == "minimal":
        return scrubbed, None
    max_len = _FULL_BODY_MAX if capture_level == "full_local" else _REDACTED_BODY_MAX
    body = truncate_text(scrubbed, max_len)
    return scrubbed if capture_level != "off" else None, body
