"""Tests for template visibility and tags in the library store."""

from __future__ import annotations

from pathlib import Path

import pytest

from ylang.library import open_library
from ylang.library.types import TemplateParam


@pytest.fixture
def library(tmp_path: Path):
    lib = open_library(tmp_path / "library.db")
    yield lib
    lib.close()


def test_seed_templates_default_public_with_tags(library) -> None:
    template = library.recall("summarize")
    assert template is not None
    assert template.visibility == "public"
    assert "summarize" in template.tags


def test_user_template_defaults_private(library) -> None:
    template = library.save(
        "user-default",
        name="User Default",
        body="plain",
        params=[],
        source="user",
    )
    assert template.visibility == "private"
    assert template.tags == ()


def test_user_template_visibility_and_tags_overridable(library) -> None:
    template = library.save(
        "user-custom",
        name="Custom",
        body="Do {task}",
        params=[TemplateParam(name="task", description="Task")],
        source="user",
        visibility="public",
        tags=["edit_file", "refactor"],
    )
    assert template.visibility == "public"
    assert template.tags == ("edit_file", "refactor")

    listed = library.list(visibility="public")
    ids = {item.template_id for item in listed}
    assert "user-custom" in ids
    assert "summarize" in ids

    private_only = library.list(visibility="private")
    private_ids = {item.template_id for item in private_only}
    assert "user-custom" not in private_ids


def test_save_new_version_preserves_visibility_when_omitted(library) -> None:
    library.save(
        "versioned-vis",
        name="V1",
        body="one",
        params=[],
        source="user",
        visibility="public",
        tags=["alpha"],
    )
    updated = library.save(
        "versioned-vis",
        name="V2",
        body="two",
        params=[],
        source="user",
    )
    assert updated.version == 2
    assert updated.visibility == "public"
    assert updated.tags == ("alpha",)


def test_migration_adds_columns_on_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    lib = open_library(db_path)
    lib.close()

    from ylang.core.db import open_connection

    conn = open_connection(db_path)
    conn.execute("DROP TABLE IF EXISTS template_versions")
    conn.execute("DROP TABLE IF EXISTS templates")
    conn.executescript(
        """
        CREATE TABLE templates (
            template_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            latest_version INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE template_versions (
            template_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            body TEXT NOT NULL,
            params_json TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (template_id, version)
        );
        """
    )
    conn.commit()
    conn.close()

    migrated = open_library(db_path)
    columns = {
        row[1]
        for row in migrated._connection.execute(
            "PRAGMA table_info(templates)"
        ).fetchall()
    }
    assert "visibility" in columns
    assert "tags_json" in columns
    migrated.close()


def test_archived_visibility_and_list_exclusion(library) -> None:
    library.save(
        "archived-user",
        name="Archived",
        body="hidden",
        params=[],
        source="user",
        visibility="archived",
    )
    archived = library.recall("archived-user")
    assert archived is not None
    assert archived.visibility == "archived"

    active_ids = {item.template_id for item in library.list()}
    assert "archived-user" not in active_ids
    assert "archived-user" in {
        item.template_id for item in library.list(visibility="archived")
    }


def test_set_visibility_archives_without_new_version(library) -> None:
    library.save(
        "to-archive",
        name="Archive me",
        body="body",
        params=[],
        source="user",
        visibility="public",
    )
    assert library.set_visibility("to-archive", "archived") is True
    assert library.recall("to-archive").visibility == "archived"
    assert library.recall("to-archive").version == 1


def test_migration_expands_visibility_check(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-vis.db"
    from ylang.core.db import open_connection

    conn = open_connection(db_path)
    conn.execute("DROP TABLE IF EXISTS template_versions")
    conn.execute("DROP TABLE IF EXISTS templates")
    conn.executescript(
        """
        CREATE TABLE templates (
            template_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            latest_version INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            visibility TEXT NOT NULL DEFAULT 'private'
                CHECK (visibility IN ('public', 'private')),
            tags_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE template_versions (
            template_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            body TEXT NOT NULL,
            params_json TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (template_id, version)
        );
        """
    )
    conn.commit()
    conn.close()

    migrated = open_library(db_path)
    migrated.save(
        "legacy-user",
        name="Legacy",
        body="body",
        params=[],
        source="user",
    )
    migrated.set_visibility("legacy-user", "archived")
    assert migrated.recall("legacy-user").visibility == "archived"
    migrated.close()
