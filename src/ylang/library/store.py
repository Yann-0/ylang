"""SQLite-backed versioned prompt template library."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Self

from ylang.core.db import open_connection
from ylang.library.seeds import ensure_seeds
from ylang.library.types import (
    Template,
    TemplateParam,
    TemplateSource,
    TemplateSummary,
    TemplateVisibility,
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS templates (
    template_id    TEXT PRIMARY KEY,
    name           TEXT    NOT NULL,
    latest_version INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT    NOT NULL,
    visibility     TEXT    NOT NULL DEFAULT 'private'
        CHECK (visibility IN ('public', 'private')),
    tags_json      TEXT    NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS template_versions (
    template_id  TEXT    NOT NULL,
    version      INTEGER NOT NULL,
    body         TEXT    NOT NULL,
    params_json  TEXT    NOT NULL,
    source       TEXT    NOT NULL CHECK (source IN ('seed', 'user', 'learned')),
    created_at   TEXT    NOT NULL,
    PRIMARY KEY (template_id, version),
    FOREIGN KEY (template_id) REFERENCES templates(template_id)
);

CREATE INDEX IF NOT EXISTS idx_template_versions_source
    ON template_versions (source);
"""

def _open_connection(db_path: Path) -> sqlite3.Connection:
    return open_connection(db_path)


def from_connection(connection: sqlite3.Connection, *, ensure_seed_data: bool = True) -> Library:
    """Attach a library store to an existing SQLite connection."""
    library = Library(connection)
    library._ensure_schema()
    if ensure_seed_data:
        ensure_seeds(library)
    return library


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None:
        msg = "datetime must be timezone-aware"
        raise ValueError(msg)
    if value.utcoffset() != timedelta(0):
        msg = "datetime must be UTC"
        raise ValueError(msg)


def _to_iso(value: datetime) -> str:
    _require_utc(value)
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    _require_utc(parsed)
    return parsed


def _params_to_json(params: list[TemplateParam]) -> str:
    payload = [
        {
            "name": param.name,
            "description": param.description,
            "default": param.default,
        }
        for param in params
    ]
    return json.dumps(payload)


def _params_from_json(raw: str) -> list[TemplateParam]:
    items = json.loads(raw)
    return [
        TemplateParam(
            name=str(item["name"]),
            description=str(item.get("description", "")),
            default=item.get("default"),
        )
        for item in items
    ]


def _tags_to_json(tags: list[str]) -> str:
    return json.dumps(list(tags))


def _tags_from_json(raw: str) -> tuple[str, ...]:
    items = json.loads(raw)
    return tuple(str(item) for item in items)


def _default_visibility(source: TemplateSource) -> TemplateVisibility:
    if source == "seed":
        return "public"
    return "private"


class Library:
    """Local versioned prompt template store."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._list_cache: dict[tuple[TemplateSource | None, TemplateVisibility | None], list[TemplateSummary]] = {}

    def clear_list_cache(self) -> None:
        """Clear the in-memory template list cache (primarily for tests)."""
        self._list_cache.clear()

    @classmethod
    def open(cls, db_path: Path) -> Self:
        """Open (or create) the library tables at db_path."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = _open_connection(db_path)
        library = cls(connection)
        library._ensure_schema()
        ensure_seeds(library)
        return library

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    def _ensure_schema(self) -> None:
        self._connection.executescript(_SCHEMA_SQL)
        columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(templates)").fetchall()
        }
        if "visibility" not in columns:
            self._connection.execute(
                """
                ALTER TABLE templates
                ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'
                    CHECK (visibility IN ('public', 'private'))
                """
            )
        if "tags_json" not in columns:
            self._connection.execute(
                "ALTER TABLE templates ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
            )
        self._connection.commit()

    def save(
        self,
        template_id: str,
        *,
        name: str,
        body: str,
        params: list[TemplateParam],
        source: TemplateSource,
        visibility: TemplateVisibility | None = None,
        tags: list[str] | None = None,
        _internal_learned: bool = False,
    ) -> Template:
        """Append a new immutable version for template_id."""
        if source == "learned" and not _internal_learned:
            msg = "source='learned' is reserved for the pattern-detection pipeline"
            raise ValueError(msg)
        now = datetime.now(timezone.utc)
        row = self._connection.execute(
            """
            SELECT latest_version, visibility, tags_json
            FROM templates WHERE template_id = ?
            """,
            (template_id,),
        ).fetchone()
        version = 1 if row is None else int(row[0]) + 1
        if row is None:
            resolved_visibility = visibility if visibility is not None else _default_visibility(source)
            resolved_tags = list(tags) if tags is not None else []
        else:
            resolved_visibility = (
                visibility if visibility is not None else row[1]  # type: ignore[arg-type]
            )
            resolved_tags = list(tags) if tags is not None else list(_tags_from_json(str(row[2])))
        params_json = _params_to_json(params)
        tags_json = _tags_to_json(resolved_tags)
        self._connection.execute(
            """
            INSERT INTO template_versions (
                template_id, version, body, params_json, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (template_id, version, body, params_json, source, _to_iso(now)),
        )
        if row is None:
            self._connection.execute(
                """
                INSERT INTO templates (
                    template_id, name, latest_version, updated_at, visibility, tags_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    name,
                    version,
                    _to_iso(now),
                    resolved_visibility,
                    tags_json,
                ),
            )
        else:
            self._connection.execute(
                """
                UPDATE templates
                SET name = ?, latest_version = ?, updated_at = ?,
                    visibility = ?, tags_json = ?
                WHERE template_id = ?
                """,
                (name, version, _to_iso(now), resolved_visibility, tags_json, template_id),
            )
        self._connection.commit()
        self._list_cache.clear()
        return Template(
            template_id=template_id,
            name=name,
            version=version,
            body=body,
            params=list(params),
            source=source,
            created_at=now,
            visibility=resolved_visibility,
            tags=tuple(resolved_tags),
        )

    def recall(
        self,
        template_id: str,
        *,
        version: int | None = None,
    ) -> Template | None:
        """Return a specific version, or the latest when version is None."""
        if version is None:
            row = self._connection.execute(
                """
                SELECT t.name, t.latest_version
                FROM templates t
                WHERE t.template_id = ?
                """,
                (template_id,),
            ).fetchone()
            if row is None:
                return None
            version = int(row[1])
        fetched = self._connection.execute(
            """
            SELECT
                t.name, tv.version, tv.body, tv.params_json, tv.source, tv.created_at,
                t.visibility, t.tags_json
            FROM template_versions tv
            JOIN templates t ON t.template_id = tv.template_id
            WHERE tv.template_id = ? AND tv.version = ?
            """,
            (template_id, version),
        ).fetchone()
        if fetched is None:
            return None
        params = _params_from_json(str(fetched[3]))
        return Template(
            template_id=template_id,
            name=str(fetched[0]),
            version=int(fetched[1]),
            body=str(fetched[2]),
            params=params,
            source=fetched[4],  # type: ignore[arg-type]
            created_at=_from_iso(str(fetched[5])),
            visibility=fetched[6],  # type: ignore[arg-type]
            tags=_tags_from_json(str(fetched[7])),
        )

    def list(
        self,
        *,
        source: TemplateSource | None = None,
        visibility: TemplateVisibility | None = None,
    ) -> list[TemplateSummary]:
        """Return latest-version metadata for each template."""
        cache_key = (source, visibility)
        cached = self._list_cache.get(cache_key)
        if cached is not None:
            return cached
        rows = self._connection.execute(
            """
            SELECT
                t.template_id,
                t.name,
                t.latest_version,
                t.updated_at,
                tv.source,
                tv.params_json,
                t.visibility,
                t.tags_json
            FROM templates t
            JOIN template_versions tv
                ON t.template_id = tv.template_id AND t.latest_version = tv.version
            WHERE (? IS NULL OR tv.source = ?)
              AND (? IS NULL OR t.visibility = ?)
            ORDER BY t.template_id
            """,
            (source, source, visibility, visibility),
        ).fetchall()
        summaries: list[TemplateSummary] = []
        for row in rows:
            params = _params_from_json(str(row[5]))
            summaries.append(
                TemplateSummary(
                    template_id=str(row[0]),
                    name=str(row[1]),
                    latest_version=int(row[2]),
                    source=row[4],  # type: ignore[arg-type]
                    updated_at=_from_iso(str(row[3])),
                    param_names=tuple(param.name for param in params),
                    visibility=row[6],  # type: ignore[arg-type]
                    tags=_tags_from_json(str(row[7])),
                )
            )
        self._list_cache[cache_key] = summaries
        return summaries

    def render(
        self,
        template_id: str,
        param_values: dict[str, str],
        *,
        version: int | None = None,
    ) -> str:
        """Recall a template and substitute named params (defaults fill missing keys)."""
        template = self.recall(template_id, version=version)
        if template is None:
            msg = f"template not found: {template_id}"
            raise KeyError(msg)
        values: dict[str, str] = {}
        for param in template.params:
            if param.name in param_values:
                values[param.name] = param_values[param.name]
            elif param.default is not None:
                values[param.name] = param.default
            else:
                msg = f"missing required param: {param.name}"
                raise KeyError(msg)
        return template.body.format(**values)


def open_library(db_path: Path) -> Library:
    """Open the prompt library at the given path."""
    return Library.open(db_path)


def save_learned_template(
    library: Library,
    template_id: str,
    *,
    name: str,
    body: str,
    params: list[TemplateParam],
) -> Template:
    """Save a learned template from the pattern-detection pipeline."""
    return library.save(
        template_id,
        name=name,
        body=body,
        params=params,
        source="learned",
        _internal_learned=True,
    )
