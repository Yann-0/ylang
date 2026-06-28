"""Single typed settings object for ylang."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

McpTransport = Literal["stdio", "http"]


class Settings(BaseModel):
    """Application configuration loaded from environment variables."""

    storage_path: Path = Field(
        default=Path("~/.ylang/ylang.db"),
        description="Local SQLite database path.",
    )
    transport: McpTransport = Field(
        default="stdio",
        description="MCP transport: stdio (local subprocess) or http (streamable HTTP).",
    )
    host: str = Field(
        default="0.0.0.0",
        description="Bind host when transport is http.",
    )
    port: int = Field(
        default=8787,
        ge=1,
        le=65535,
        description="Bind port when transport is http.",
    )
    auth_token: str | None = Field(
        default=None,
        description="Bearer token required for http transport.",
    )

    @classmethod
    def load(cls) -> Settings:
        """Build settings from environment variables and defaults."""
        kwargs: dict[str, object] = {}

        raw_path = os.environ.get("YLANG_STORAGE_PATH")
        if raw_path is not None:
            kwargs["storage_path"] = Path(raw_path)

        if raw_transport := os.environ.get("YLANG_TRANSPORT"):
            kwargs["transport"] = raw_transport

        if raw_host := os.environ.get("YLANG_HOST"):
            kwargs["host"] = raw_host

        if raw_port := os.environ.get("YLANG_PORT"):
            kwargs["port"] = int(raw_port)

        if raw_token := os.environ.get("YLANG_AUTH_TOKEN"):
            kwargs["auth_token"] = raw_token

        return cls(**kwargs)

    def resolved_storage_path(self) -> Path:
        """Return the expanded, absolute storage path."""
        return self.storage_path.expanduser().resolve()
