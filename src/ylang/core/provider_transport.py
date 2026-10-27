"""Single-request direct HTTPS transport with bounded response size and deadline."""
from __future__ import annotations

import http.client
import queue
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Protocol

ALLOWED_ENDPOINTS = {
    "api.openai.com": "/v1/chat/completions",
    "api.anthropic.com": "/v1/messages",
    "api.mistral.ai": "/v1/chat/completions",
}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class HTTPReply:
    """Provider status and bounded native bytes, without authentication material."""
    status: int
    body: bytes
    request_id: str | None = None


class ProviderTransport(Protocol):
    """Exactly one native request; fixture implementations explicitly declare live=False."""
    live: bool

    def post(self, host: str, path: str, headers: dict[str, str], body: bytes,
             timeout: float) -> HTTPReply:
        """Return one reply without retries, redirects, proxy discovery or caching."""
        ...


class ProviderTransportError(RuntimeError):
    """The dispatched attempt has unknown billing and must retain its hold."""


def _remaining(deadline: float) -> float:
    """Apply one monotonic deadline to DNS, connect, TLS, send and receive."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("provider request deadline exceeded")
    return remaining


def _resolve_address(host: str, deadline: float) -> tuple:
    """Bound DNS waiting; the daemon only resolves and can never send a request."""
    results: queue.Queue[object] = queue.Queue(maxsize=1)

    def resolve() -> None:
        """Return DNS evidence without opening a socket or dispatching HTTP."""
        try:
            results.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except Exception as exc:
            results.put(exc)

    threading.Thread(target=resolve, name="ylang-provider-dns", daemon=True).start()
    try:
        result = results.get(timeout=_remaining(deadline))
    except queue.Empty as exc:
        raise TimeoutError("provider DNS deadline exceeded") from exc
    _remaining(deadline)
    if isinstance(result, Exception):
        raise ProviderTransportError("provider DNS resolution failed") from result
    if not isinstance(result, list) or not result:
        raise ProviderTransportError("provider DNS returned no address")
    return result[0]


class DirectHTTPSProviderTransport:
    """Fixed direct HTTPS POST; the owner alone can open/send the provider request."""
    live = True

    def post(self, host: str, path: str, headers: dict[str, str], body: bytes,
             timeout: float) -> HTTPReply:
        """Dispatch once, bound response bytes, and interrupt reads at the total deadline."""
        if ALLOWED_ENDPOINTS.get(host) != path:
            raise ValueError("unsupported provider endpoint")
        if type(timeout) not in (int, float) or not 0 < timeout <= 60:
            raise ValueError("provider deadline must be positive and at most 60 seconds")
        if not isinstance(body, bytes) or len(body) > 1024 * 1024:
            raise ValueError("provider request body exceeds supported byte bound")
        if any(not isinstance(k, str) or not isinstance(v, str)
               or any(c in k + v for c in "\r\n\x00") for k, v in headers.items()):
            raise ValueError("invalid provider headers")
        deadline = time.monotonic() + timeout
        family, socktype, protocol, _, address = _resolve_address(host, deadline)
        raw = socket.socket(family, socktype, protocol)
        connection: http.client.HTTPSConnection | None = None
        timer: threading.Timer | None = None
        active: socket.socket = raw
        try:
            raw.settimeout(_remaining(deadline))
            raw.connect(address)
            raw.settimeout(_remaining(deadline))
            active = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
            active.settimeout(_remaining(deadline))
            connection = http.client.HTTPSConnection(host, timeout=_remaining(deadline))
            connection.sock = active

            def interrupt() -> None:
                """Stop owner-thread I/O at deadline; this callback cannot dispatch."""
                try:
                    active.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = threading.Timer(_remaining(deadline), interrupt)
            timer.daemon = True
            timer.start()
            _remaining(deadline)
            connection.request("POST", path, body=body, headers=headers)
            active.settimeout(_remaining(deadline))
            response = connection.getresponse()
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > MAX_RESPONSE_BYTES):
                raise ProviderTransportError("provider response exceeds byte limit")
            parts: list[bytes] = []
            size = 0
            while True:
                active.settimeout(_remaining(deadline))
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                _remaining(deadline)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ProviderTransportError("provider response exceeds byte limit")
                parts.append(chunk)
            request_id = response.getheader("request-id") or response.getheader("x-request-id")
            if request_id is not None:
                request_id = request_id[:256]
            return HTTPReply(response.status, b"".join(parts), request_id)
        finally:
            if timer is not None:
                timer.cancel()
            if connection is not None:
                connection.close()
            active.close()
            raw.close()
