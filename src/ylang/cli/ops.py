"""Operational CLI: backup, export, import, doctor."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from ylang import __version__

from ylang.console.import_ops import import_json_payload
from ylang.core.db import verify_storage_writable
from ylang.core.stores import open_stores
from ylang.settings import Settings, provider_has_key


def build_backup_parser() -> argparse.ArgumentParser:
    """Build ``ylang backup`` parser."""
    parser = argparse.ArgumentParser(
        prog="ylang backup", description="Backup SQLite database"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination .db file path",
    )
    return parser


def build_export_parser() -> argparse.ArgumentParser:
    """Build ``ylang export`` parser."""
    parser = argparse.ArgumentParser(
        prog="ylang export", description="Export templates and facts as JSON"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination JSON file",
    )
    return parser


def build_import_parser() -> argparse.ArgumentParser:
    """Build ``ylang import`` parser."""
    parser = argparse.ArgumentParser(
        prog="ylang import", description="Import templates and facts from JSON"
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Source JSON file from ylang export",
    )
    return parser


def build_doctor_parser() -> argparse.ArgumentParser:
    """Build ``ylang doctor`` parser."""
    return argparse.ArgumentParser(
        prog="ylang doctor", description="Check local Ylang environment"
    )


def run_backup_cli(argv: list[str] | None = None) -> int:
    """Backup the SQLite database using the online backup API."""
    args = build_backup_parser().parse_args(argv)
    settings = Settings.load()
    source = settings.resolved_storage_path()
    destination = args.output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    verify_storage_writable(source)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    print(f"Backup written to {destination}", file=sys.stderr)
    return 0


def run_export_cli(argv: list[str] | None = None) -> int:
    """Export templates and facts to JSON."""
    args = build_export_parser().parse_args(argv)
    stores, _ = _open_stores()
    try:
        templates = []
        for summary in stores.library.list():
            template = stores.library.recall(summary.template_id)
            if template is None:
                continue
            templates.append(
                {
                    "template_id": template.template_id,
                    "name": template.name,
                    "body": template.body,
                    "params": [
                        {
                            "name": p.name,
                            "description": p.description,
                            "default": p.default,
                        }
                        for p in template.params
                    ],
                    "source": template.source,
                    "visibility": template.visibility,
                    "tags": list(template.tags),
                }
            )
        facts = [
            {
                "fact": fact.fact,
                "scope": fact.scope,
                "workspace": getattr(fact, "workspace", ""),
                "created_at": fact.created_at.isoformat(),
            }
            for fact in stores.memory.recall(limit=10_000)
        ]
        payload = {"version": 1, "templates": templates, "facts": facts}
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            f"Exported {len(templates)} templates and {len(facts)} facts",
            file=sys.stderr,
        )
        return 0
    finally:
        stores.close()


def run_import_cli(argv: list[str] | None = None) -> int:
    """Import templates and facts from JSON export."""
    args = build_import_parser().parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    stores, _ = _open_stores()
    try:
        imported_templates, imported_facts = import_json_payload(
            stores.library,
            stores.memory,
            payload,
        )
        print(
            f"Imported {imported_templates} templates and {imported_facts} facts",
            file=sys.stderr,
        )
        return 0
    finally:
        stores.close()


def run_doctor_cli(argv: list[str] | None = None) -> int:
    """Run environment diagnostics."""
    build_doctor_parser().parse_args(argv)
    settings = Settings.load()
    ok = True
    db_path = settings.resolved_storage_path()
    print(f"Storage: {db_path}")
    try:
        verify_storage_writable(db_path)
        print("  ✓ database path writable")
    except OSError as exc:
        ok = False
        print(f"  ✗ {exc}")

    configured = settings.provider_keys.configured_names()
    if configured:
        print(f"LLM providers: {', '.join(configured)}")
    else:
        print("LLM providers: (none configured)")
        ok = False

    fallback = settings.fallback_model
    if provider_has_key(
        fallback, settings.provider_keys
    ) or fallback.lower().startswith("ollama/"):
        print(f"Fallback model: {fallback} ✓")
    else:
        print(f"Fallback model: {fallback} (may need provider key)")

    if settings.transport == "http":
        if settings.auth_token:
            print("HTTP auth token: set ✓")
        else:
            ok = False
            print("HTTP auth token: missing ✗")
        print(f"HTTP bind: {settings.host}:{settings.port}")
        port = settings.port
        if _port_free(settings.host, port):
            print(f"Port {port}: available ✓")
        else:
            print(f"Port {port}: in use (service may already run)")
        base_url = f"http://127.0.0.1:{port}"
        health = _fetch_json(f"{base_url}/health")
        if health is not None:
            running_version = str(health.get("version", "unknown"))
            print(f"Running service version: {running_version}")
            if running_version != __version__:
                print(
                    f"  ⚠ Installed package is v{__version__} but service reports "
                    f"v{running_version} — run: sudo systemctl restart ylang"
                )
        login_status = _http_status(f"{base_url}/console/login")
        if login_status == 200:
            print("Console login page: reachable ✓")
        elif login_status == 401:
            ok = False
            print(
                "Console login page: 401 Unauthorized ✗ "
                "(stale service or missing v0.5+ console routes — restart ylang)"
            )
        elif login_status is not None:
            print(f"Console login page: HTTP {login_status}")

    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    if _ollama_reachable(ollama_host):
        print(f"Ollama ({ollama_host}): reachable ✓")
    else:
        print(f"Ollama ({ollama_host}): not reachable")

    if os.environ.get("YLANG_HOOK_DISABLED") != "1" and settings.transport == "http":
        print(
            "⚠ Hooks + HTTP gateway: set YLANG_HOOK_DISABLED=1 on gateway-only clients "
            "to avoid double LLM calls"
        )

    return 0 if ok else 1


def _open_stores():
    settings = Settings.load()
    return open_stores(settings.resolved_storage_path()), settings


def _port_free(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host if host != "0.0.0.0" else "127.0.0.1", port))
        return True
    except OSError:
        return False


def _ollama_reachable(host: str) -> bool:
    parsed = urlparse(host)
    hostname = parsed.hostname or "localhost"
    port = parsed.port or 11434
    try:
        with socket.create_connection((hostname, port), timeout=2):
            return True
    except OSError:
        return False


def _fetch_json(url: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def _http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError):
        return None
