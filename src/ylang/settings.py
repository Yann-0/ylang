"""Single typed settings object for ylang."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Application configuration loaded from environment variables."""

    storage_path: Path = Field(
        default=Path("~/.ylang/ylang.db"),
        description="Local SQLite database path.",
    )

    @classmethod
    def load(cls) -> Settings:
        """Build settings from environment variables and defaults."""
        raw_path = os.environ.get("YLANG_STORAGE_PATH")
        if raw_path is None:
            return cls()
        return cls(storage_path=Path(raw_path))

    def resolved_storage_path(self) -> Path:
        """Return the expanded, absolute storage path."""
        return self.storage_path.expanduser().resolve()
