"""SQLite-backed versioned prompt template library."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Self

from ylang.library.seeds import ensure_seeds
from ylang.library.types import Template, TemplateParam, TemplateSource, TemplateSummary

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS templates (
    template_id    TEXT PRIMARY KEY,
    name           TEXT    NOT NULL,
    latest_version INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT    NOT NULL
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
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


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


class Library:
    """Local versioned prompt template store."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

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
        self._connection.commit()

    def save(
        self,
        template_id: str,
        *,
        name: str,
        body: str,
        params: list[TemplateParam],
        source: TemplateSource,
    ) -> Template:
        """Append a new immutable version for template_id."""
        if source == "learned":
            msg = "source='learned' is reserved for the future pattern-detection hook"
            raise ValueError(msg)
        now = datetime.now(timezone.utc)
        row = self._connection.execute(
            "SELECT latest_version FROM templates WHERE template_id = ?",
            (template_id,),
        ).fetchone()
        version = 1 if row is None else int(row[0]) + 1
        params_json = _params_to_json(params)
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
                INSERT INTO templates (template_id, name, latest_version, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (template_id, name, version, _to_iso(now)),
            )
        else:
            self._connection.execute(
                """
                UPDATE templates
                SET name = ?, latest_version = ?, updated_at = ?
                WHERE template_id = ?
                """,
                (name, version, _to_iso(now), template_id),
            )
        self._connection.commit()
        return Template(
            template_id=template_id,
            name=name,
            version=version,
            body=body,
            params=list(params),
            source=source,
            created_at=now,
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
            SELECT t.name, tv.version, tv.body, tv.params_json, tv.source, tv.created_at
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
        )

    def list(
        self,
        *,
        source: TemplateSource | None = None,
    ) -> list[TemplateSummary]:
        """Return latest-version metadata for each template."""
        rows = self._connection.execute(
            """
            SELECT
                t.template_id,
                t.name,
                t.latest_version,
                t.updated_at,
                tv.source,
                tv.params_json
            FROM templates t
            JOIN template_versions tv
                ON t.template_id = tv.template_id AND t.latest_version = tv.version
            WHERE ? IS NULL OR tv.source = ?
            ORDER BY t.template_id
            """,
            (source, source),
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
                )
            )
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
