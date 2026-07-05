"""Operational CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

from ylang.cli.ops import run_backup_cli, run_doctor_cli, run_export_cli
from ylang.core.stores import open_stores


def test_backup_and_export_import_roundtrip(db_path: Path, monkeypatch) -> None:
    stores = open_stores(db_path)
    stores.library.save(
        "demo",
        name="Demo",
        body="Hello {{name}}",
        params=[],
        source="user",
    )
    stores.memory.remember("likes python", "shareable", workspace="/proj")
    stores.close()

    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    backup_path = db_path.with_name("backup.db")
    assert run_backup_cli(["--output", str(backup_path)]) == 0
    assert backup_path.is_file()

    export_path = db_path.with_name("export.json")
    assert run_export_cli(["--output", str(export_path)]) == 0
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert len(payload["templates"]) >= 1
    demo = next(item for item in payload["templates"] if item["template_id"] == "demo")
    assert demo["body"] == "Hello {{name}}"
    assert payload["facts"][0]["workspace"] == "/proj"


def test_doctor_reports_storage(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    open_stores(db_path).close()
    assert run_doctor_cli([]) == 0
