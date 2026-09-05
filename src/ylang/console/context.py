"""Shared console request context for route modules."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from starlette.responses import HTMLResponse

from ylang.console.layout import ConsoleNavContext, console_nav_scope
from ylang.core.engine import Engine
from ylang.core.runtime_settings import (
    RuntimeSettingsStore,
    effective_feature_flags,
    merge_settings,
)
from ylang.settings import Settings

if TYPE_CHECKING:
    from ylang.mcp.deps import YlangDeps

BOOL_FORM_KEYS = frozenset(
    {
        "improver_critique",
        "experiments",
        "edit_feedback",
        "usage_digest_enabled",
    }
)
PATTERN_CACHE_KEY = "_console_pattern_cache"
STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass
class ConsoleContext:
    """Mutable bundle shared by console route registrars."""

    server: FastMCP
    deps: YlangDeps
    settings: Settings
    engine: Engine
    runtime_store: RuntimeSettingsStore

    def reconnect_stores_after_restore(self) -> bool:
        """Reopen SQLite handles after an on-disk database swap."""
        database = self.deps.store._database
        if database is None:
            return False
        try:
            database.reconnect()
        except OSError:
            return False
        connection = database.connection
        self.deps.store._connection = connection
        self.deps.library._connection = connection
        self.deps.memory._connection = connection
        self.runtime_store._connection = connection
        return True

    def effective_settings(self) -> Settings:
        """Env settings merged with runtime SQLite overrides."""
        return merge_settings(self.settings, self.runtime_store.as_dict())

    def setup_checks(self) -> list[tuple[str, bool, str]]:
        """Shared onboarding checklist for Setup page and nav prominence."""
        eff = self.effective_settings()
        return [
            ("Python", sys.version_info >= (3, 12), sys.version.split()[0]),
            (
                "LLM providers",
                bool(eff.provider_keys.configured_names()),
                ", ".join(eff.provider_keys.configured_names()) or "none",
            ),
            (
                "Auth token",
                bool(self.settings.auth_token),
                "set" if self.settings.auth_token else "missing",
            ),
            (
                "Storage",
                self.settings.resolved_storage_path().parent.exists(),
                str(self.settings.resolved_storage_path()),
            ),
        ]

    def nav_context(self) -> ConsoleNavContext:
        """Build nav flags from effective feature settings and setup checks."""
        flags = effective_feature_flags(self.runtime_store.as_dict())
        checks = self.setup_checks()
        return ConsoleNavContext(
            experiments_enabled=bool(flags.get("experiments")),
            edit_feedback_enabled=bool(flags.get("edit_feedback")),
            setup_complete=all(ok for _, ok, _ in checks),
        )

    def render(self, build: Callable[[], str]) -> HTMLResponse:
        """Build page HTML inside a nav scope, then return an HTML response."""
        with console_nav_scope(self.nav_context()):
            return HTMLResponse(build())
