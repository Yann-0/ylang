"""Client-supplied correlation helpers for control-plane traces."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

PARENT_TRACE_HEADER = "x-ylang-parent-trace"
TRACE_ID_HEADER = "x-ylang-trace-id"


def parent_trace_from_request(
    request: Request,
    body: dict[str, Any] | None = None,
) -> str | None:
    """Read optional parent trace id from header or JSON body (no invention)."""
    header = request.headers.get(PARENT_TRACE_HEADER)
    if header and header.strip():
        return header.strip()
    if body:
        for key in ("parent_trace_id", "ylang_parent_trace_id"):
            raw = body.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def trace_id_from_request(
    request: Request,
    body: dict[str, Any] | None = None,
) -> str | None:
    """Read optional client-allocated trace id from header or JSON body."""
    header = request.headers.get(TRACE_ID_HEADER)
    if header and header.strip():
        return header.strip()
    if body:
        for key in ("trace_id", "ylang_trace_id"):
            raw = body.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None
