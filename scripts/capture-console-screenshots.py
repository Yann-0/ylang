#!/usr/bin/env python3
"""Capture full-page screenshots of every Ylang console route for docs.

Requires:
  - Ylang HTTP server reachable (default http://127.0.0.1:8787)
  - playwright + Chromium: ``pip install playwright && playwright install chromium``
  - Auth token via ``YLANG_AUTH_TOKEN`` or ``--token``

Writes PNGs under ``docs/images/console/``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _load_token(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("YLANG_AUTH_TOKEN")
    if env:
        return env
    for candidate in (
        Path("/srv/ylang/ylang.env"),
        Path.cwd().parent / "ylang.env",
        Path.home() / ".ylang" / "ylang.env",
    ):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.startswith("YLANG_AUTH_TOKEN="):
                return line.split("=", 1)[1].strip()
    msg = "YLANG_AUTH_TOKEN not set; pass --token or export the variable"
    raise SystemExit(msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("YLANG_BASE_URL", "http://127.0.0.1:8787"),
    )
    parser.add_argument("--token", default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "images" / "console",
    )
    args = parser.parse_args(argv)
    token = _load_token(args.token)
    args.out.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install playwright: pip install playwright && playwright install chromium", file=sys.stderr)
        return 1

    pages = [
        ("login", "/console/login"),
        ("today", "/console/today"),
        ("quality", "/console/quality"),
        ("routing", "/console/routing"),
        ("control", "/console/control"),
        ("overview", "/console"),
        ("usage", "/console/usage"),
        ("improver", "/console/improver"),
        ("templates", "/console/templates"),
        ("facts", "/console/facts"),
        ("patterns", "/console/patterns"),
        ("proposals", "/console/proposals"),
        ("privacy", "/console/privacy"),
        ("experiments", "/console/experiments"),
        ("feedback", "/console/feedback"),
        ("settings", "/console/settings"),
        ("data", "/console/data?table=usage"),
        ("advisor", "/console/advisor"),
        ("ops", "/console/ops"),
        ("setup", "/console/setup"),
        ("health", "/console/health"),
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.goto(f"{args.base_url}/console/login", wait_until="networkidle")
        page.fill('input[name="token"]', token)
        page.click('button[type="submit"]')
        page.wait_for_url("**/console**", timeout=15_000)

        for name, path in pages:
            if name == "login":
                login_ctx = browser.new_context(
                    viewport={"width": 1400, "height": 900}
                )
                login_page = login_ctx.new_page()
                login_page.goto(
                    f"{args.base_url}/console/login", wait_until="networkidle"
                )
                login_page.screenshot(
                    path=str(args.out / f"{name}.png"), full_page=True
                )
                login_ctx.close()
                print(f"wrote {name}.png")
                continue
            page.goto(
                f"{args.base_url}{path}",
                wait_until="networkidle",
                timeout=30_000,
            )
            page.wait_for_timeout(400)
            page.screenshot(path=str(args.out / f"{name}.png"), full_page=True)
            print(f"wrote {name}.png")
        browser.close()

    print(f"screenshots saved under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
