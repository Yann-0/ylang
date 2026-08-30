#!/srv/ylang/app/.venv/bin/python3
"""Cursor ``beforeSubmitPrompt`` hook: call Ylang ``improve_prompt`` on user messages.

Reads ``YLANG_MCP_URL`` / ``YLANG_AUTH_TOKEN`` (from ``sessionStart`` hook env or
``~/.cursor/mcp.json``). Skips ``/loop``, ``/YOLO``, ``/ylang-skip``, meta prompts,
and reference-only ``@file`` lines. An inline ``ylang-off`` / ``/ylang-off``
instruction anywhere in the prompt bypasses improvement and is stripped from the
submitted text. Fail-open: errors and timeouts log to
``~/.cursor/hooks/ylang-improve-prompt.log`` and return ``continue: true``.
MCP calls honor ``YLANG_HOOK_TIMEOUT_SEC`` (default 15s).

Writes the latest result to ``.cursor/ylang-improved-prompt.md`` in the workspace.
Passes ``session_id`` / ``workspace`` / ``parent_trace_id`` into MCP ``improve_prompt``
for control-plane correlation (Cursor ``conversation_id``, ``workspace_roots``,
prior turn ``trace_id``).

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
from typing import Any, Mapping

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from ylang.improver.reference import is_reference_only_prompt

_HOOK_LOG = Path.home() / ".cursor" / "hooks" / "ylang-improve-prompt.log"
_IMPROVED_FILENAME = "ylang-improved-prompt.md"
_LAST_TRACE_FILENAME = "ylang-last-trace.json"
_TRACE_ID_RE = re.compile(
    r"^-+\s*trace_id:\s*`?([0-9a-fA-F-]{8,})`?\s*$",
    re.MULTILINE,
)
_SKIP_PREFIXES = ("/loop", "/YOLO", "/ylang-skip")
_META_MARKERS = (
    "ylang-auto-improve generated=",
    "Ylang improved task specification",
    "rejection_reason:",
    "## Original prompt",
)
_USER_QUERY_RE = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL)
_TIMESTAMP_RE = re.compile(r"<timestamp>.*?</timestamp>\s*", re.DOTALL)
# Match ylang-off / /ylang-off as a token (not inside longer identifiers).
_YLANG_OFF_RE = re.compile(r"(?<![\w-])/?ylang-off(?![\w-])", re.IGNORECASE)
_DEFAULT_HOOK_TIMEOUT_SEC = 15.0


def _hook_timeout_sec() -> float:
    """Return MCP call timeout in seconds (``YLANG_HOOK_TIMEOUT_SEC``, default 15)."""
    raw = os.environ.get("YLANG_HOOK_TIMEOUT_SEC", "").strip()
    if not raw:
        return _DEFAULT_HOOK_TIMEOUT_SEC
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_HOOK_TIMEOUT_SEC
    return max(1.0, value)


def _env_flag_truthy(environ: Mapping[str, str], key: str) -> bool:
    """Return True when ``environ[key]`` is a common truthy string."""
    return environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}


def _should_capture_edit_feedback(environ: Mapping[str, str] | None = None) -> bool:
    """Return True when the hook should record edit distance via ``record_prompt_edit``.

    Capture is on when either ``YLANG_CAPTURE_EDIT_FEEDBACK`` or
    ``YLANG_EDIT_FEEDBACK`` is truthy. The former is the primary hook/service
    env; the latter mirrors the console runtime ``edit_feedback`` flag name
    for operators who set both layers the same way.
    """
    env = environ if environ is not None else os.environ
    return _env_flag_truthy(env, "YLANG_CAPTURE_EDIT_FEEDBACK") or _env_flag_truthy(
        env, "YLANG_EDIT_FEEDBACK"
    )


async def _run_timed(coro: Any, *, label: str) -> Any:
    """Await ``coro`` with a hook timeout; raise ``TimeoutError`` when exceeded."""
    timeout = _hook_timeout_sec()
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError as exc:
        raise TimeoutError(f"{label} timed out after {timeout}s") from exc


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
    explicit = (
        str(payload.get("composer_mode") or payload.get("mode") or "").strip().lower()
    )
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


def _has_ylang_off(prompt: str) -> bool:
    """Return True when the prompt contains an inline ``ylang-off`` instruction."""
    return _YLANG_OFF_RE.search(prompt) is not None


def _strip_ylang_off(prompt: str) -> str:
    """Remove ``ylang-off`` / ``/ylang-off`` tokens and tidy leftover whitespace."""
    cleaned = _YLANG_OFF_RE.sub(" ", prompt)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _should_skip(prompt: str) -> bool:
    """Return True when the hook should not call improve_prompt at all."""
    stripped = prompt.strip()
    if not stripped:
        return True
    if _is_hook_meta_prompt(stripped):
        return True
    if os.environ.get("YLANG_HOOK_DISABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return True
    lowered = stripped.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in _SKIP_PREFIXES)


def _is_reference_passthrough(prompt: str) -> bool:
    """Return True for bare file/terminal pointers that should not be LLM-improved."""
    return is_reference_only_prompt(prompt.strip())


def _project_cursor_dir() -> Path:
    """Return ``.cursor`` under the active project (or cwd)."""
    project_dir = os.environ.get("CURSOR_PROJECT_DIR") or os.getcwd()
    return Path(project_dir) / ".cursor"


def _improved_prompt_path() -> Path:
    return _project_cursor_dir() / _IMPROVED_FILENAME


def _last_trace_path() -> Path:
    return _project_cursor_dir() / _LAST_TRACE_FILENAME


def _first_nonempty_str(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _workspace_label(payload: Mapping[str, Any]) -> str | None:
    """Derive a workspace label from Cursor roots or project dir."""
    roots = payload.get("workspace_roots")
    if isinstance(roots, list) and roots:
        root = str(roots[0] or "").strip()
        if root:
            return Path(root).name or root
    project = os.environ.get("CURSOR_PROJECT_DIR", "").strip()
    if project:
        return Path(project).name or project
    return None


def _read_prior_trace_id() -> str | None:
    """Load parent ``trace_id`` from last-trace JSON or improved-prompt sidecar."""
    path = _last_trace_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                tid = _first_nonempty_str(data.get("trace_id"))
                if tid:
                    return tid
    except (OSError, json.JSONDecodeError):
        pass
    improved = _improved_prompt_path()
    try:
        if improved.is_file():
            match = _TRACE_ID_RE.search(improved.read_text(encoding="utf-8"))
            if match:
                return match.group(1)
    except OSError:
        pass
    return _first_nonempty_str(os.environ.get("YLANG_LAST_TRACE_ID"))


def _write_last_trace(
    *,
    trace_id: str,
    session_id: str | None,
    workspace: str | None,
) -> None:
    path = _last_trace_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "trace_id": trace_id,
        "session_id": session_id,
        "workspace": workspace,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _correlation_from_payload(payload: Mapping[str, Any]) -> dict[str, str | None]:
    """Extract session / workspace / parent_trace for MCP improve_prompt."""
    session_id = _first_nonempty_str(
        payload.get("session_id"),
        payload.get("conversation_id"),
        os.environ.get("YLANG_SESSION_ID"),
    )
    workspace = _first_nonempty_str(
        payload.get("workspace"),
        _workspace_label(payload),
        os.environ.get("YLANG_WORKSPACE"),
    )
    parent_trace_id = _first_nonempty_str(
        payload.get("parent_trace_id"),
        payload.get("parent_trace"),
        _read_prior_trace_id(),
    )
    return {
        "session_id": session_id,
        "workspace": workspace,
        "parent_trace_id": parent_trace_id,
    }


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
    session_id: str | None = None,
    workspace: str | None = None,
    trace_id: str | None = None,
    parent_trace_id: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    rejection_line = (
        f"- rejection_reason: `{rejection_reason}`\n" if rejection_reason else ""
    )
    corr_lines = ""
    if session_id:
        corr_lines += f"- session_id: `{session_id}`\n"
    if workspace:
        corr_lines += f"- workspace: `{workspace}`\n"
    if trace_id:
        corr_lines += f"- trace_id: `{trace_id}`\n"
    if parent_trace_id:
        corr_lines += f"- parent_trace_id: `{parent_trace_id}`\n"
    body = (
        f"<!-- ylang-auto-improve generated={stamp} -->\n"
        f"# Ylang improved task specification\n\n"
        f"Follow this document as the **canonical task** for the current user turn.\n"
        f"The raw chat message may be a rough draft.\n\n"
        f"- cursor_mode: `{cursor_mode}`\n"
        f"- mode_source: `{mode_source or 'unknown'}`\n"
        f"- validated: `{validated}`\n"
        f"- changed: `{changed}`\n"
        f"{rejection_line}"
        f"{corr_lines}\n"
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
    session_id: str | None = None,
    workspace: str | None = None,
    parent_trace_id: str | None = None,
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
    else:
        if session_id:
            args["session_id"] = session_id
        if workspace:
            args["workspace"] = workspace
        if parent_trace_id:
            args["parent_trace_id"] = parent_trace_id

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


def _run_main() -> None:
    """Parse stdin hook payload, call ``improve_prompt``, and emit Cursor JSON."""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        _log("invalid stdin JSON; fail-open")
        _fail_open()
        return

    prompt = str(payload.get("prompt") or "").strip()
    if _has_ylang_off(prompt):
        cleaned = _strip_ylang_off(prompt)
        _log("skipped (ylang-off)")
        if cleaned and cleaned != prompt:
            print(
                json.dumps({"continue": True, "updated_input": {"prompt": cleaned}}),
                flush=True,
            )
        else:
            _fail_open()
        return

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
        correlation = _correlation_from_payload(payload)
        try:
            _write_improved_file(
                path=_improved_prompt_path(),
                original=prompt,
                improved=prompt,
                cursor_mode=mode,
                mode_source="explicit",
                validated=True,
                changed=False,
                session_id=correlation.get("session_id"),
                workspace=correlation.get("workspace"),
                parent_trace_id=correlation.get("parent_trace_id"),
            )
        except OSError as exc:
            _log(f"failed to write improved prompt file: {exc}")
        _log(
            f"passthrough mode={mode} validated=True changed=False (file/terminal reference)"
        )
        _fail_open()
        return

    mode = _resolve_mode(payload)
    tool = f"cursor-{mode}"
    model = os.environ.get("YLANG_HOOK_MODEL", "auto").strip() or "auto"
    conversation = _conversation_from_transcript(
        os.environ.get("CURSOR_TRANSCRIPT_PATH")
    )
    correlation = _correlation_from_payload(payload)
    session_id = correlation.get("session_id")
    workspace = correlation.get("workspace")
    parent_trace_id = correlation.get("parent_trace_id")

    try:
        mcp_url, auth_token = _load_mcp_config()
        result = asyncio.run(
            _run_timed(
                _call_improve_prompt(
                    mcp_url=mcp_url,
                    auth_token=auth_token,
                    text=prompt,
                    tool=tool,
                    mode=mode,
                    conversation=conversation,
                    model=model,
                    session_id=session_id,
                    workspace=workspace,
                    parent_trace_id=parent_trace_id,
                ),
                label="improve_prompt",
            )
        )
    except TimeoutError as exc:
        _log(f"improve_prompt timed out: {exc}")
        _fail_open()
        return
    except Exception as exc:  # noqa: BLE001 - hook must fail open
        _log(f"improve_prompt failed: {exc}")
        traceback.print_exc(file=sys.stderr)
        _fail_open()
        return

    auto_apply = bool(result.get("auto_apply_default", True))
    improved = str(result.get("improved") or prompt).strip()
    original = str(result.get("original") or prompt).strip()
    cursor_mode = str(result.get("cursor_mode") or mode)
    mode_source = result.get("mode_source")
    validated = bool(result.get("validated", False))
    rejection_reason = result.get("rejection_reason")
    rejection_text = str(rejection_reason).strip() if rejection_reason else None
    changed = improved != original
    trace_id = _first_nonempty_str(result.get("trace_id"))

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
            session_id=session_id,
            workspace=workspace,
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
        )
    except OSError as exc:
        _log(f"failed to write improved prompt file: {exc}")

    if trace_id:
        try:
            _write_last_trace(
                trace_id=trace_id,
                session_id=session_id,
                workspace=workspace,
            )
        except OSError as exc:
            _log(f"failed to write last-trace file: {exc}")

    reason_suffix = f" reason={rejection_text!r}" if rejection_text else ""
    corr_suffix = ""
    if session_id:
        corr_suffix += f" session={session_id}"
    if workspace:
        corr_suffix += f" workspace={workspace}"
    if trace_id:
        corr_suffix += f" trace={trace_id}"
    _log(
        f"improved mode={cursor_mode} validated={validated} "
        f"changed={changed}{reason_suffix}{corr_suffix}"
    )

    if changed and validated:
        try:
            asyncio.run(
                _run_timed(
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
                    ),
                    label="record improver_accepted",
                )
            )
            _log("recorded improver_accepted=true")
        except TimeoutError as exc:
            _log(f"record improver_accepted timed out: {exc}")
        except Exception as exc:  # noqa: BLE001 - hook must fail open
            _log(f"record improver_accepted failed: {exc}")

    # Polish samples: compare improved vs what will be submitted after this hook.
    # auto_apply (or unchanged) → submitted=improved (kept-as-is, distance 0);
    # review path → user continues with the original prompt.
    if _should_capture_edit_feedback() and improved:
        submitted = improved if auto_apply else prompt
        try:
            asyncio.run(
                _run_timed(
                    _record_edit_feedback(mcp_url, auth_token, improved, submitted),
                    label="record prompt edit feedback",
                )
            )
            _log(
                "recorded prompt edit feedback "
                f"(kept_as_is={submitted.strip() == improved.strip()})"
            )
        except TimeoutError as exc:
            _log(f"record prompt edit feedback timed out: {exc}")
        except Exception as exc:  # noqa: BLE001 - hook must fail open
            _log(f"record prompt edit feedback failed: {exc}")

    # Cursor hook output: honor auto_apply_default from improve_prompt.
    # When false + changed+validated: surface user_message for review instead of silent apply.
    output: dict[str, Any] = {"continue": True}
    if improved and improved != original:
        if auto_apply:
            output["updated_input"] = {"prompt": improved}
        else:
            output["user_message"] = (
                "Ylang improved your prompt — review the sidecar file "
                f"(.cursor/{_IMPROVED_FILENAME}) before continuing:\n\n"
                f"{improved}"
            )
    print(json.dumps(output), flush=True)


def main() -> None:
    """Run the hook; always fail-open on unexpected errors."""
    try:
        _run_main()
    except Exception:
        _log("unhandled hook error; fail-open")
        traceback.print_exc(file=sys.stderr)
        _fail_open()


if __name__ == "__main__":
    main()
