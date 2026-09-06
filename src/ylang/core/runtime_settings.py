"""Hot-reloadable runtime settings stored in SQLite."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ylang.core.config_parsers import parse_bool_flag, parse_model_list
from ylang.settings import Settings
from ylang.usage.capture import parse_capture_level

HOT_RELOADABLE_KEYS: frozenset[str] = frozenset(
    {
        "daily_budget_usd",
        "quality_band",
        "fallback_model",
        "provider_cooldown_seconds",
        "pattern_detector",
        "learned_template_limit",
        "retrieval_preferred_template_ids",
        "improver_critique",
        "improver_timeout_sec",
        "experiments",
        "edit_feedback",
        "rate_limit_per_minute",
        "models_code",
        "models_search",
        "models_reason",
        "models_improve",
        "models_other",
        "pattern_alert_threshold",
        "usage_digest_enabled",
        "usage_digest_last_at",
        "capture_level",
    }
)

RESTART_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "storage_path",
        "transport",
        "host",
        "port",
        "auth_token",
        "auth_token_previous",
        "openai_api_key",
        "anthropic_api_key",
        "mistral_api_key",
        "perplexity_api_key",
        "gemini_api_key",
        "otel_enabled",
        "otel_endpoint",
        "otel_export_content",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeSettingRow:
    """One persisted runtime override."""

    key: str
    value: str
    updated_at: datetime


class RuntimeSettingsStore:
    """Read/write hot-reloadable settings overrides in SQLite."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, key: str) -> str | None:
        """Return the stored value for ``key``, or ``None`` when unset."""
        cursor = self._connection.execute(
            "SELECT value FROM runtime_settings WHERE key = ?",
            (key,),
        )
        row = cursor.fetchone()
        return str(row[0]) if row is not None else None

    def set(self, key: str, value: str) -> RuntimeSettingRow:
        """Upsert a runtime setting and return the stored row."""
        now = datetime.now(timezone.utc).isoformat()
        self._connection.execute(
            """
            INSERT INTO runtime_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        self._connection.commit()
        return RuntimeSettingRow(
            key=key, value=value, updated_at=datetime.fromisoformat(now)
        )

    def delete(self, key: str) -> bool:
        """Remove a runtime override; return True when a row was deleted."""
        cursor = self._connection.execute(
            "DELETE FROM runtime_settings WHERE key = ?",
            (key,),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def list_all(self) -> list[RuntimeSettingRow]:
        """Return all runtime overrides ordered by key."""
        cursor = self._connection.execute(
            "SELECT key, value, updated_at FROM runtime_settings ORDER BY key"
        )
        rows: list[RuntimeSettingRow] = []
        for key, value, updated_at in cursor.fetchall():
            rows.append(
                RuntimeSettingRow(
                    key=str(key),
                    value=str(value),
                    updated_at=datetime.fromisoformat(str(updated_at)),
                )
            )
        return rows

    def as_dict(self) -> dict[str, str]:
        """Return all overrides as a flat dict."""
        return {row.key: row.value for row in self.list_all()}


def _parse_bool(raw: str | None) -> bool | None:
    return parse_bool_flag(raw)


def _parse_model_list(raw: str) -> list[str]:
    return parse_model_list(raw, require_non_empty=False)


def get_effective_settings(base: Settings, overrides: dict[str, str]) -> Settings:
    """Return env settings merged with runtime SQLite overrides (authority order).

    Resolution: **environment (`Settings`) → runtime overrides → effective**.
    Prefer this name at call sites for clarity; equivalent to ``merge_settings``.
    """
    return merge_settings(base, overrides)


def merge_settings(base: Settings, overrides: dict[str, str]) -> Settings:
    """Return a copy of ``base`` with runtime overrides applied where supported."""
    data = base.model_dump()
    if budget := overrides.get("daily_budget_usd"):
        try:
            data["daily_budget_usd"] = float(budget)
        except ValueError:
            pass
    if band := overrides.get("quality_band"):
        try:
            data["quality_band"] = int(band)
        except ValueError:
            pass
    if fallback := overrides.get("fallback_model"):
        data["fallback_model"] = fallback.strip()
    if cooldown := overrides.get("provider_cooldown_seconds"):
        try:
            data["provider_cooldown_seconds"] = int(cooldown)
        except ValueError:
            pass
    if capture := overrides.get("capture_level"):
        data["capture_level"] = parse_capture_level(
            capture, default=data.get("capture_level", "minimal")
        )
    activity_lists = dict(data["activity_model_lists"])
    activity_env_map = {
        "models_code": "code",
        "models_search": "search",
        "models_reason": "reason",
        "models_improve": "improve",
        "models_other": "other",
    }
    for override_key, activity in activity_env_map.items():
        if raw := overrides.get(override_key):
            models = _parse_model_list(raw)
            if models:
                activity_lists[activity] = models
    data["activity_model_lists"] = activity_lists
    return Settings(**data)


def effective_feature_flags(overrides: dict[str, str]) -> dict[str, bool]:
    """Return resolved feature flags from runtime overrides and defaults."""
    return {
        "improver_critique": _parse_bool(overrides.get("improver_critique")) or False,
        "experiments": _parse_bool(overrides.get("experiments")) or False,
        "edit_feedback": _parse_bool(overrides.get("edit_feedback")) or False,
    }


def effective_int_setting(
    key: str,
    *,
    env_var: str | None = None,
    default: int = 0,
    overrides: dict[str, str] | None = None,
) -> int:
    """Resolve an integer setting: runtime override, then env, then ``default``."""
    if overrides is not None:
        raw = overrides.get(key)
        if raw is not None and raw.strip():
            try:
                return int(raw.strip())
            except ValueError:
                pass
    if env_var is not None:
        raw = os.environ.get(env_var)
        if raw is not None and raw.strip():
            try:
                return int(raw.strip())
            except ValueError:
                pass
    return default


def mask_secret(value: str | None, *, visible: int = 4, max_bullets: int = 12) -> str:
    """Mask a secret for display, showing only the last ``visible`` characters.

    Bullet count is capped so long API keys do not blow out console table layout.
    """
    if not value:
        return "(not set)"
    if len(value) <= visible:
        return "•" * len(value)
    bullets = min(len(value) - visible, max_bullets)
    return "•" * bullets + value[-visible:]


SETTING_DESCRIPTIONS: dict[str, str] = {
    "daily_budget_usd": "Rolling 24h spend cap in USD; cloud models skipped when exceeded.",
    "quality_band": "Rank offset for cost tie-break within the quality-ordered model list.",
    "fallback_model": "Local LiteLLM floor model when cloud routes fail.",
    "provider_cooldown_seconds": "Seconds to skip a provider after retryable LLM failure.",
    "pattern_detector": "Pattern clustering mode: lexical (difflib) or semantic (TF-IDF).",
    "learned_template_limit": "Max learned templates injected into improver context.",
    "retrieval_preferred_template_ids": (
        "Comma-separated template ids boosted in improver reference retrieval."
    ),
    "improver_critique": "Second-pass self-critique on improver output.",
    "improver_timeout_sec": (
        "Wall-clock budget (seconds) for improver LLM calls; 0 disables. "
        "Default 12; keep below YLANG_HOOK_TIMEOUT_SEC (15)."
    ),
    "experiments": "A/B improver system prompt variants.",
    "edit_feedback": "Capture edit distance between improved and submitted prompts.",
    "rate_limit_per_minute": "Per-IP HTTP rate limit (0 disables).",
    "models_code": "Comma-separated models for code activity routing.",
    "models_search": "Comma-separated models for search activity routing.",
    "models_reason": "Comma-separated models for reason activity routing.",
    "models_improve": (
        "Comma-separated models for all improve:* improver routing "
        "(prefer faster/cheaper models first)."
    ),
    "models_other": "Comma-separated models for other activity routing.",
    "pattern_alert_threshold": "Minimum pattern occurrences before console alert badge.",
    "usage_digest_enabled": (
        "When on, `ylang usage digest` attempts a desktop notification "
        "(`notify-send`) if a display is available. Digests are still CLI/cron only — "
        "the console does not email or push."
    ),
    "usage_digest_last_at": "ISO timestamp of the last digest run (updated by CLI).",
    "capture_level": (
        "Trace privacy capture: off | minimal | redacted | full_local "
        "(default minimal; raw bodies only when redacted/full_local)."
    ),
}


def restart_required_snapshot(settings: Settings) -> dict[str, str]:
    """Return read-only env-derived values for the console settings page."""
    keys = settings.provider_keys
    return {
        "storage_path": str(settings.resolved_storage_path()),
        "transport": settings.transport,
        "host": settings.host,
        "port": str(settings.port),
        "auth_token": mask_secret(settings.auth_token),
        "auth_token_previous": mask_secret(settings.auth_token_previous),
        "openai_api_key": mask_secret(keys.openai),
        "anthropic_api_key": mask_secret(keys.anthropic),
        "mistral_api_key": mask_secret(keys.mistral),
        "perplexity_api_key": mask_secret(keys.perplexity),
    }


def serialize_runtime_row(row: RuntimeSettingRow) -> dict[str, Any]:
    """Serialize a runtime setting row for JSON/API output."""
    return {
        "key": row.key,
        "value": row.value,
        "updated_at": row.updated_at.isoformat(),
    }
