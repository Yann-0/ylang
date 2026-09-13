"""Allowlists, licenses, and scheduled-refresh network policy."""

from __future__ import annotations

from urllib.parse import urlparse

from ylang.importer.source_types import (
    ADAPTER_VERSION,
    MANUAL_SOURCE_ID,
    POLICY_VERSION,
    PromptSource,
)

HTTPS_SCHEME = "https"
MAX_REDIRECTS = 3
DEFAULT_TIMEOUT_SEC = 30
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024
MAX_TREE_BYTES = 5 * 1024 * 1024
MAX_INGEST_ITEMS = 200_000
REFRESH_LEASE_TTL_SEC = 600
USER_AGENT = "Ylang-PromptIntelligence/0.7 (+https://github.com/Yann-0/ylang)"

COPILOT_INCOMPATIBLE_NOTE = (
    "LIVE_SOURCE 2026-09-13 github/awesome-copilot@7568a482ce2d: 0 *.prompt.md "
    "files; tree is agents/skills/instructions/extensions. v1 will not convert "
    "those into ordinary prompts."
)

SCHEDULED_HOSTS: frozenset[str] = frozenset(
    {
        "api.github.com",
        "raw.githubusercontent.com",
    }
)

SOURCE_URL_PREFIXES: dict[str, tuple[str, ...]] = {
    "prompts-chat": (
        "https://api.github.com/repos/f/prompts.chat/",
        "https://api.github.com/repos/f/awesome-chatgpt-prompts/",
        "https://raw.githubusercontent.com/f/prompts.chat/",
        "https://raw.githubusercontent.com/f/awesome-chatgpt-prompts/",
    ),
    "github-awesome-copilot": (
        "https://api.github.com/repos/github/awesome-copilot/",
        "https://raw.githubusercontent.com/github/awesome-copilot/",
    ),
    "fabric-patterns": (
        "https://api.github.com/repos/danielmiessler/Fabric/",
        "https://raw.githubusercontent.com/danielmiessler/Fabric/",
    ),
}

LICENSE_MARKERS: dict[str, tuple[str, ...]] = {
    "CC0-1.0": (
        "cc0",
        "creative commons zero",
        "public domain dedication",
        "cc0 1.0",
    ),
    "MIT": (
        "mit license",
        "permission is hereby granted, free of charge",
    ),
}

EXPECTED_CONTENT_TYPES: dict[str, tuple[str, ...]] = {
    "csv": ("text/csv", "text/plain", "application/octet-stream", ""),
    "json": ("application/json", "text/plain", "application/vnd.github+json", ""),
    "markdown": ("text/markdown", "text/plain", "application/octet-stream", ""),
    "license": ("text/plain", "text/markdown", "application/octet-stream", ""),
}

BUILTIN_SOURCE_SPECS: tuple[dict[str, object], ...] = (
    {
        "source_id": "prompts-chat",
        "name": "prompts.chat",
        "adapter": "prompts-chat",
        "canonical_url": "https://github.com/f/prompts.chat",
        "repo_url": "https://github.com/f/prompts.chat",
        "license_spdx": "CC0-1.0",
        "license_url": "https://github.com/f/prompts.chat/blob/main/LICENSE",
        "trust_tier": "community-broad",
        "enabled": 0,
        "refresh_interval_hours": 24,
        "policy_version": POLICY_VERSION,
    },
    {
        "source_id": "github-awesome-copilot",
        "name": "GitHub awesome-copilot",
        "adapter": "github-awesome-copilot",
        "canonical_url": "https://github.com/github/awesome-copilot",
        "repo_url": "https://github.com/github/awesome-copilot",
        "license_spdx": "MIT",
        "license_url": "https://github.com/github/awesome-copilot/blob/main/LICENSE",
        "trust_tier": "curated-coding",
        "enabled": 0,
        "refresh_interval_hours": 24,
        "policy_version": POLICY_VERSION,
        "compatibility_status": "incompatible",
        "compatibility_note": COPILOT_INCOMPATIBLE_NOTE,
    },
    {
        "source_id": "fabric-patterns",
        "name": "Fabric patterns",
        "adapter": "fabric-patterns",
        "canonical_url": "https://github.com/danielmiessler/Fabric",
        "repo_url": "https://github.com/danielmiessler/Fabric",
        "license_spdx": "MIT",
        "license_url": "https://github.com/danielmiessler/Fabric/blob/main/LICENSE",
        "trust_tier": "curated-patterns",
        "enabled": 0,
        "refresh_interval_hours": 168,
        "policy_version": POLICY_VERSION,
    },
    {
        "source_id": MANUAL_SOURCE_ID,
        "name": "Manual CSV import",
        "adapter": "csv-manual",
        "canonical_url": "local://manual-import",
        "repo_url": None,
        "license_spdx": "unknown",
        "license_url": None,
        "trust_tier": "manual",
        "enabled": 0,
        "refresh_interval_hours": 0,
        "policy_version": POLICY_VERSION,
    },
)


class SourcePolicyError(ValueError):
    """Raised when a scheduled fetch or license check violates policy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _strip_url(url: str) -> str:
    return url.strip()


def validate_fetch_url(url: str, *, source_id: str | None) -> str:
    """Validate a fetch URL. Scheduled sources use an explicit allowlist."""
    target = _strip_url(url)
    parsed = urlparse(target)
    if parsed.scheme != HTTPS_SCHEME:
        raise SourcePolicyError(
            "scheme",
            f"scheduled fetch requires HTTPS, got {parsed.scheme or 'none'}",
        )
    host = (parsed.hostname or "").lower()
    if source_id is None or source_id == MANUAL_SOURCE_ID:
        if parsed.scheme != HTTPS_SCHEME:
            raise SourcePolicyError("scheme", "manual URL import requires HTTPS")
        return target
    if host not in SCHEDULED_HOSTS:
        raise SourcePolicyError("host", f"host not allowlisted for scheduled fetch: {host}")
    prefixes = SOURCE_URL_PREFIXES.get(source_id, ())
    if not prefixes:
        raise SourcePolicyError("source", f"no URL allowlist for source {source_id}")
    if not any(target.startswith(prefix) for prefix in prefixes):
        raise SourcePolicyError(
            "prefix",
            f"URL not in allowlist for {source_id}: {target}",
        )
    return target


def license_text_matches(text: str, spdx: str) -> bool:
    """Return True when license text contains expected SPDX markers."""
    markers = LICENSE_MARKERS.get(spdx)
    if not markers:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def content_type_allowed(content_type: str | None, kind: str) -> bool:
    """Return True when Content-Type is empty or in the expected set."""
    allowed = EXPECTED_CONTENT_TYPES.get(kind)
    if allowed is None:
        return True
    raw = (content_type or "").split(";", 1)[0].strip().lower()
    if raw == "":
        return True
    return raw in allowed


def is_scheduled_source(source: PromptSource) -> bool:
    """Return True when the source may be included in ``refresh --all``."""
    return source.source_id != MANUAL_SOURCE_ID and source.adapter != "csv-manual"


def scheduled_license_required(source: PromptSource) -> bool:
    """Scheduled sources always require a license check (fail closed)."""
    return is_scheduled_source(source)


def license_policy_error(source: PromptSource) -> str | None:
    """Return a block reason when scheduled license policy is missing or unknown."""
    if not is_scheduled_source(source):
        return None
    spdx = (source.license_spdx or "").strip()
    if not spdx or spdx.lower() == "unknown":
        return "unknown or missing license policy blocks scheduled ingestion"
    if spdx not in LICENSE_MARKERS:
        return f"unsupported license policy {spdx} blocks scheduled ingestion"
    return None


__all__ = [
    "ADAPTER_VERSION",
    "BUILTIN_SOURCE_SPECS",
    "DEFAULT_TIMEOUT_SEC",
    "COPILOT_INCOMPATIBLE_NOTE",
    "MAX_FILE_BYTES",
    "MAX_INGEST_ITEMS",
    "MAX_REDIRECTS",
    "MAX_RESPONSE_BYTES",
    "MAX_TREE_BYTES",
    "POLICY_VERSION",
    "REFRESH_LEASE_TTL_SEC",
    "SOURCE_URL_PREFIXES",
    "SourcePolicyError",
    "USER_AGENT",
    "content_type_allowed",
    "is_scheduled_source",
    "license_policy_error",
    "license_text_matches",
    "scheduled_license_required",
    "validate_fetch_url",
]
