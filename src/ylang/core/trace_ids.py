"""Client-supplied correlation helpers for control-plane traces."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

PARENT_TRACE_HEADER = "x-ylang-parent-trace"
TRACE_ID_HEADER = "x-ylang-trace-id"
SESSION_HEADER = "x-ylang-session"
WORKSPACE_HEADER = "x-ylang-workspace"


def _optional_str_from_request(
    request: Request,
    body: dict[str, Any] | None,
    *,
    header: str,
    body_keys: tuple[str, ...],
) -> str | None:
    """Read an optional non-empty string from header or JSON body."""
    header_value = request.headers.get(header)
    if header_value and header_value.strip():
        return header_value.strip()
    if body:
        for key in body_keys:
            raw = body.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def parent_trace_from_request(
    request: Request,
    body: dict[str, Any] | None = None,
) -> str | None:
    """Read optional parent trace id from header or JSON body (no invention)."""
    return _optional_str_from_request(
        request,
        body,
        header=PARENT_TRACE_HEADER,
        body_keys=("parent_trace_id", "ylang_parent_trace_id"),
    )


def trace_id_from_request(
    request: Request,
    body: dict[str, Any] | None = None,
) -> str | None:
    """Read optional client-allocated trace id from header or JSON body."""
    return _optional_str_from_request(
        request,
        body,
        header=TRACE_ID_HEADER,
        body_keys=("trace_id", "ylang_trace_id"),
    )


def session_id_from_request(
    request: Request,
    body: dict[str, Any] | None = None,
) -> str | None:
    """Read optional session id from ``X-Ylang-Session`` or body ``session_id``."""
    return _optional_str_from_request(
        request,
        body,
        header=SESSION_HEADER,
        body_keys=("session_id", "ylang_session_id"),
    )


def workspace_from_request(
    request: Request,
    body: dict[str, Any] | None = None,
) -> str | None:
    """Read optional workspace from ``X-Ylang-Workspace`` or body ``workspace``."""
    return _optional_str_from_request(
        request,
        body,
        header=WORKSPACE_HEADER,
        body_keys=("workspace", "ylang_workspace"),
    )
