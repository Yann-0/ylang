"""Tests for dynamic prompt block assembly."""

from __future__ import annotations

from ylang.improver.block_assembler import block_type_from_tags, select_blocks
from ylang.library.store import from_connection as library_from_connection
from ylang.core.db import open_connection


def test_block_type_from_tags() -> None:
    assert block_type_from_tags(("block:constraints", "agent")) == "constraints"
    assert block_type_from_tags(("seed",)) is None


def test_select_blocks(db_path: object) -> None:
    connection = open_connection(db_path)  # type: ignore[arg-type]
    library = library_from_connection(connection)
    library.save(
        "constraints-agent",
        name="Agent constraints",
        body="Run tests before declaring done.",
        params=[],
        source="user",
        tags=["block:constraints", "agent"],
    )
    body, template_ids = select_blocks(library, cursor_mode="agent")
    assert "Run tests" in body
    assert "constraints-agent" in template_ids
