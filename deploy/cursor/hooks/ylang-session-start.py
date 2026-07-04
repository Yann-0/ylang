#!/srv/ylang/app/.venv/bin/python3
"""Cursor ``sessionStart`` hook: export Ylang MCP URL and auth for other hooks.

Prints JSON with ``env.YLANG_MCP_URL``, ``YLANG_AUTH_TOKEN``, and a default
``YLANG_HOOK_MODEL``. On failure, emits ``YLANG_HOOK_ERROR`` so the session still
starts. MCP config loading mirrors ``ylang-improve-prompt.py``.
"""

from __future__ import annotations

import json
from pathlib import Path


def _load_ylang_mcp() -> tuple[str, str]:
    """Read ylang URL and bearer token from ``~/.cursor/mcp.json``."""
    config_path = Path.home() / ".cursor" / "mcp.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    ylang = (payload.get("mcpServers") or {}).get("ylang") or {}
    url = str(ylang.get("url") or "").strip()
    headers = ylang.get("headers") or {}
    auth = str(headers.get("Authorization") or "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not url or not token:
        raise RuntimeError("ylang MCP url/token missing in ~/.cursor/mcp.json")
    return url, token


def main() -> None:
    """Load MCP settings from ``~/.cursor/mcp.json`` and print hook env JSON."""
    try:
        mcp_url, auth_token = _load_ylang_mcp()
        output = {
            "env": {
                "YLANG_MCP_URL": mcp_url,
                "YLANG_AUTH_TOKEN": auth_token,
                "YLANG_HOOK_MODEL": "claude-sonnet-4-5",
            }
        }
    except Exception as exc:  # noqa: BLE001 - session should still start
        print(json.dumps({"env": {"YLANG_HOOK_ERROR": str(exc)}}), flush=True)
        return

    print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()
