"""Interactive ``ylang init`` setup wizard."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from ylang.settings import Settings


def build_init_parser() -> argparse.ArgumentParser:
    """Build ``ylang init`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="ylang init", description="Interactive Ylang setup wizard"
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip prompts; use existing env and defaults",
    )
    return parser


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _check_python() -> tuple[bool, str]:
    version = sys.version_info
    if version >= (3, 12):
        return True, f"{version.major}.{version.minor}.{version.micro}"
    return False, f"{version.major}.{version.minor}.{version.micro} (need 3.12+)"


def _check_ollama(host: str = "http://127.0.0.1:11434") -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as response:  # noqa: S310
            return response.status == 200
    except OSError:
        return False


def _write_mcp_json(*, url: str, token: str) -> Path:
    config_dir = Path.home() / ".cursor"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "mcp.json"
    payload: dict[str, object] = {"mcpServers": {}}
    if config_path.is_file():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    servers = payload.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        payload["mcpServers"] = servers
    servers["ylang"] = {
        "url": url,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return config_path


def _copy_hooks() -> Path | None:
    repo_hooks = Path(__file__).resolve().parents[2] / "deploy" / "cursor"
    if not repo_hooks.is_dir():
        return None
    dest = Path.home() / ".cursor"
    dest.mkdir(parents=True, exist_ok=True)
    hooks_src = repo_hooks / "hooks"
    hooks_dest = dest / "hooks"
    if hooks_src.is_dir():
        hooks_dest.mkdir(parents=True, exist_ok=True)
        for item in hooks_src.glob("*.py"):
            shutil.copy2(item, hooks_dest / item.name)
    hooks_json = repo_hooks / "hooks.json"
    if hooks_json.is_file():
        shutil.copy2(hooks_json, dest / "hooks.json")
    return dest


def _console_url(settings: Settings) -> str:
    host = settings.host
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{settings.port}/console"


def run_init_cli(argv: list[str] | None = None) -> int:
    """Run the interactive setup wizard."""
    args = build_init_parser().parse_args(argv)
    settings = Settings.load()

    ok_py, py_version = _check_python()
    print(f"Python: {py_version} {'✓' if ok_py else '✗'}", file=sys.stderr)
    if not ok_py:
        return 1

    if not args.non_interactive:
        token = _prompt("YLANG_AUTH_TOKEN (HTTP bearer)", settings.auth_token or "")
        if token:
            os.environ["YLANG_AUTH_TOKEN"] = token
            settings = Settings.load()
        transport = _prompt("YLANG_TRANSPORT", settings.transport)
        if transport:
            os.environ["YLANG_TRANSPORT"] = transport
            settings = Settings.load()

    configured = settings.provider_keys.configured_names()
    print(
        f"Provider keys configured: {', '.join(configured) or '(none)'}",
        file=sys.stderr,
    )
    ollama_ok = _check_ollama()
    print(f"Ollama reachable: {'yes' if ollama_ok else 'no'}", file=sys.stderr)
    if not configured and not ollama_ok:
        print("warning: no cloud keys and Ollama not reachable", file=sys.stderr)

    if settings.transport == "http":
        if not settings.auth_token:
            print(
                "error: YLANG_AUTH_TOKEN required for HTTP transport", file=sys.stderr
            )
            return 1
        url = f"http://{settings.host}:{settings.port}/mcp"
        if settings.host in {"0.0.0.0", "::"}:
            url = f"http://127.0.0.1:{settings.port}/mcp"
        mcp_path = _write_mcp_json(url=url, token=settings.auth_token)
        print(f"Wrote MCP config: {mcp_path}", file=sys.stderr)

    hooks_path = _copy_hooks()
    if hooks_path:
        print(f"Copied Cursor hooks to {hooks_path}", file=sys.stderr)

    console = _console_url(settings)
    print(f"\nYlang console: {console}", file=sys.stderr)
    print("Start server: YLANG_TRANSPORT=http python -m ylang", file=sys.stderr)

    if settings.transport == "http":
        try:
            import urllib.request

            health_url = console.replace("/console", "/health")
            with urllib.request.urlopen(health_url, timeout=2) as response:  # noqa: S310
                if response.status == 200:
                    print("Health check: OK (server already running)", file=sys.stderr)
        except OSError:
            print(
                "Health check: server not running yet (start it manually)",
                file=sys.stderr,
            )

    return 0
