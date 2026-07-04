#!/usr/bin/env python3
"""Live smoke test for improve_prompt with a real LLM call."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ylang.core.engine import Engine
from ylang.core.stores import open_stores
from ylang.improver import Improver
from ylang.settings import Settings


def main() -> int:
    """Run a live ``improve_prompt`` smoke test against a real LLM provider."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite path (default: temp file; use production path only as ylang user)",
    )
    args = parser.parse_args()

    settings = Settings.load()
    db_path = args.db
    tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    if db_path is None:
        tmp_dir = tempfile.TemporaryDirectory(prefix="ylang-e2e-")
        db_path = Path(tmp_dir.name) / "ylang.db"

    stores = open_stores(db_path)
    engine = Engine.from_settings(stores.store, surface="e2e", settings=settings)
    improver = Improver(engine)

    prompt = (
        "Propose next steps for QuickCards after Wave 18 (all API routes migrated from "
        "supabaseAdmin to @/lib/db-admin) and Wave 19 (API routes use canonical "
        "@/repositories/* instead of @/lib/supabase-new/@/lib/supabase-client barrels). "
        "1001 unit tests passing. Remaining deferred work in "
        "docs/technical/deferred-refactor-backlog.md and docs/11_backlog.md. "
        "Context: Next.js App Router, Postgres via pg-shim, repositories in "
        "src/repositories/, deploy via scripts/docker-redeploy-web.sh."
    )
    print("Input:", prompt[:80], "...")
    result = improver.improve(prompt, "Cursor", model="claude-sonnet-4-5")

    print("validated:", result.validated)
    if result.rejection_reason:
        print("rejection_reason:", result.rejection_reason)
    print("changes:", len(result.changes))
    print("improved preview:", result.improved[:240].replace("\n", " "), "...")

    ok = (
        result.validated
        and result.improved != result.original
        and len(result.changes) > 0
    )
    stores.close()
    if tmp_dir is not None:
        tmp_dir.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
