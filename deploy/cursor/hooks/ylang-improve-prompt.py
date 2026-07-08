#!/srv/ylang/app/.venv/bin/python3
"""Cursor ``beforeSubmitPrompt`` hook: call Ylang ``improve_prompt`` on user messages.

Reads ``YLANG_MCP_URL`` / ``YLANG_AUTH_TOKEN`` (from ``sessionStart`` hook env or
``~/.cursor/mcp.json``). Skips ``/loop``, ``/YOLO``, ``/ylang-skip``, meta prompts,
and reference-only ``@file`` lines. Fail-open: errors log to
``~/.cursor/hooks/ylang-improve-prompt.log`` and return ``continue: true``.

Writes the latest result to ``.cursor/ylang-improved-prompt.md`` in the workspace.
The shebang path is deployment-specific; point hooks at your venv Python.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from ylang.improver.reference import is_reference_only_prompt

_HOOK_LOG = Path.home() / ".cursor" / "hooks" / "ylang-improve-prompt.log"
_IMPROVED_FILENAME = "ylang-improved-prompt.md"
_SKIP_PREFIXES = ("/loop", "/YOLO", "/ylang-skip")
_META_MARKERS = (
    "ylang-auto-improve generated=",
    "Ylang improved task specification",
    "rejection_reason:",
    "## Original prompt",
)
_USER_QUERY_RE = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL)
_TIMESTAMP_RE = re.compile(r"<timestamp>.*?</timestamp>\s*", re.DOTALL)


def _log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{stamp} {message}\n"
    try:
        with _HOOK_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
    print(line, file=sys.stderr, end="")


def _load_mcp_config() -> tuple[str, str]:
    url = os.environ.get("YLANG_MCP_URL", "").strip()
    token = os.environ.get("YLANG_AUTH_TOKEN", "").strip()
    if url and token:
        return url, token

    config_path = Path.home() / ".cursor" / "mcp.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to read {config_path}: {exc}") from exc

    servers = payload.get("mcpServers") or {}
    ylang = servers.get("ylang") or {}
    url = str(ylang.get("url") or "").strip()
    headers = ylang.get("headers") or {}
    auth = str(headers.get("Authorization") or "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not url or not token:
        raise RuntimeError("ylang MCP url/token missing in env and ~/.cursor/mcp.json")
    return url, token


def _strip_cursor_message(text: str) -> str:
    match = _USER_QUERY_RE.search(text)
    if match:
        return match.group(1).strip()
    return _TIMESTAMP_RE.sub("", text).strip()


def _conversation_from_transcript(path: str | None) -> list[dict[str, str]]:
    if not path:
        return []
    transcript = Path(path)
    if not transcript.is_file():
        return []

    turns: list[dict[str, str]] = []
    try:
        for raw_line in transcript.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "turn_ended":
                continue
            role = row.get("role")
            if role not in {"user", "assistant"}:
                continue
            message = row.get("message") or {}
            parts: list[str] = []
            for item in message.get("content") or []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "text":
                    continue
                text = _strip_cursor_message(str(item.get("text") or ""))
                if text:
                    parts.append(text)
            if parts:
                turns.append({"role": str(role), "content": "\n".join(parts)})
    except OSError as exc:
        _log(f"transcript read failed: {exc}")
        return []

    return turns[-20:]


def _resolve_mode(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("composer_mode") or payload.get("mode") or "").strip().lower()
    aliases = {
        "chat": "ask",
        "ask": "ask",
        "agent": "agent",
        "plan": "plan",
        "debug": "debug",
        "multitask": "multitask",
    }
    if explicit in aliases:
        return aliases[explicit]
    return "agent"


def _is_hook_meta_prompt(prompt: str) -> bool:
    """Return True when the user pasted Ylang hook diagnostic output, not a task."""
    hits = sum(1 for marker in _META_MARKERS if marker in prompt)
    return hits >= 2


def _should_skip(prompt: str) -> bool:
    """Return True when the hook should not call improve_prompt at all."""
    stripped = prompt.strip()
    if not stripped:
        return True
    if _is_hook_meta_prompt(stripped):
        return True
    if os.environ.get("YLANG_HOOK_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return True
    lowered = stripped.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in _SKIP_PREFIXES)


def _is_reference_passthrough(prompt: str) -> bool:
    """Return True for bare file/terminal pointers that should not be LLM-improved."""
    return is_reference_only_prompt(prompt.strip())


def _improved_prompt_path() -> Path:
    project_dir = os.environ.get("CURSOR_PROJECT_DIR") or os.getcwd()
    return Path(project_dir) / ".cursor" / _IMPROVED_FILENAME


def _write_improved_file(
    *,
    path: Path,
    original: str,
    improved: str,
    cursor_mode: str,
    mode_source: str | None,
    validated: bool,
    rejection_reason: str | None = None,
    changed: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    rejection_line = (
        f"- rejection_reason: `{rejection_reason}`\n"
        if rejection_reason
        else ""
    )
    body = (
        f"<!-- ylang-auto-improve generated={stamp} -->\n"
        f"# Ylang improved task specification\n\n"
        f"Follow this document as the **canonical task** for the current user turn.\n"
        f"The raw chat message may be a rough draft.\n\n"
        f"- cursor_mode: `{cursor_mode}`\n"
        f"- mode_source: `{mode_source or 'unknown'}`\n"
        f"- validated: `{validated}`\n"
        f"- changed: `{changed}`\n"
        f"{rejection_line}\n"
        f"## Improved prompt\n\n"
        f"{improved.strip()}\n\n"
        f"## Original prompt\n\n"
        f"{original.strip()}\n"
    )
    path.write_text(body, encoding="utf-8")


async def _call_improve_prompt(
    *,
    mcp_url: str,
    auth_token: str,
    text: str,
    tool: str,
    mode: str,
    conversation: list[dict[str, str]],
    model: str,
    accepted: bool = False,
    record_acceptance_only: bool = False,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {auth_token}"}
    args: dict[str, Any] = {
        "text": text,
        "tool": tool,
        "model": model,
        "use_context": True,
        "mode": mode,
        "accepted": accepted,
        "record_acceptance_only": record_acceptance_only,
    }
    if conversation:
        args["conversation"] = conversation
    if record_acceptance_only:
        args["use_context"] = False

    async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("improve_prompt", args)
            payload = result.structuredContent
            if not isinstance(payload, dict):
                raise RuntimeError(f"unexpected improve_prompt payload: {payload!r}")
            return payload


async def _record_edit_feedback(
    mcp_url: str,
    auth_token: str,
    improved: str,
    submitted: str,
) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool(
                "record_prompt_edit",
                {"original_text": improved, "submitted_text": submitted},
            )


def _fail_open() -> None:
    print(json.dumps({"continue": True}), flush=True)


def main() -> None:
    """Parse stdin hook payload, call ``improve_prompt``, and emit Cursor JSON."""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        _log("invalid stdin JSON; fail-open")
        _fail_open()
        return

    prompt = str(payload.get("prompt") or "").strip()
    if _should_skip(prompt):
        reason = (
            "skipped (hook meta/diagnostic prompt)"
            if _is_hook_meta_prompt(prompt.strip())
            else "skipped (empty, disabled, or command prefix)"
        )
        _log(reason)
        _fail_open()
        return

    if _is_reference_passthrough(prompt):
        mode = _resolve_mode(payload)
        try:
            _write_improved_file(
                path=_improved_prompt_path(),
                original=prompt,
                improved=prompt,
                cursor_mode=mode,
                mode_source="explicit",
                validated=True,
                changed=False,
            )
        except OSError as exc:
            _log(f"failed to write improved prompt file: {exc}")
        _log(f"passthrough mode={mode} validated=True changed=False (file/terminal reference)")
        _fail_open()
        return

    mode = _resolve_mode(payload)
    tool = f"cursor-{mode}"
    model = os.environ.get("YLANG_HOOK_MODEL", "claude-sonnet-4-5").strip() or "claude-sonnet-4-5"
    conversation = _conversation_from_transcript(os.environ.get("CURSOR_TRANSCRIPT_PATH"))

    try:
        mcp_url, auth_token = _load_mcp_config()
        result = asyncio.run(
            _call_improve_prompt(
                mcp_url=mcp_url,
                auth_token=auth_token,
                text=prompt,
                tool=tool,
                mode=mode,
                conversation=conversation,
                model=model,
            )
        )
    except Exception as exc:  # noqa: BLE001 - hook must fail open
        _log(f"improve_prompt failed: {exc}")
        traceback.print_exc(file=sys.stderr)
        _fail_open()
        return

    improved = str(result.get("improved") or prompt).strip()
    original = str(result.get("original") or prompt).strip()
    cursor_mode = str(result.get("cursor_mode") or mode)
    mode_source = result.get("mode_source")
    validated = bool(result.get("validated", False))
    rejection_reason = result.get("rejection_reason")
    rejection_text = str(rejection_reason).strip() if rejection_reason else None
    changed = improved != original

    try:
        _write_improved_file(
            path=_improved_prompt_path(),
            original=original,
            improved=improved,
            cursor_mode=cursor_mode,
            mode_source=str(mode_source) if mode_source is not None else None,
            validated=validated,
            rejection_reason=rejection_text,
            changed=changed,
        )
    except OSError as exc:
        _log(f"failed to write improved prompt file: {exc}")

    reason_suffix = f" reason={rejection_text!r}" if rejection_text else ""
    _log(
        f"improved mode={cursor_mode} validated={validated} "
        f"changed={changed}{reason_suffix}"
    )

    if changed and validated:
        try:
            asyncio.run(
                _call_improve_prompt(
                    mcp_url=mcp_url,
                    auth_token=auth_token,
                    text=original,
                    tool=tool,
                    mode=mode,
                    conversation=[],
                    model=model,
                    accepted=True,
                    record_acceptance_only=True,
                )
            )
            _log("recorded improver_accepted=true")
        except Exception as exc:  # noqa: BLE001 - hook must fail open
            _log(f"record improver_accepted failed: {exc}")

    if (
        os.environ.get("YLANG_CAPTURE_EDIT_FEEDBACK", "").strip().lower() in {"1", "true", "yes"}
        and improved
        and prompt.strip() != improved.strip()
    ):
        try:
            asyncio.run(_record_edit_feedback(mcp_url, auth_token, improved, prompt))
            _log("recorded prompt edit feedback")
        except Exception as exc:  # noqa: BLE001 - hook must fail open
            _log(f"record prompt edit feedback failed: {exc}")

    # Cursor currently documents only `continue`/`user_message` for this hook.
    # We also emit `updated_input` for forward compatibility if Cursor adds support.
    output: dict[str, Any] = {"continue": True}
    if improved and improved != original:
        output["updated_input"] = {"prompt": improved}
    print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()
