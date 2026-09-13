"""HTTPS fetch with allowlists, bounded redirects, size and timeout limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from ylang.importer.policy import (
    DEFAULT_TIMEOUT_SEC,
    MAX_REDIRECTS,
    MAX_RESPONSE_BYTES,
    SourcePolicyError,
    USER_AGENT,
    content_type_allowed,
    validate_fetch_url,
)


class FetchError(OSError):
    """Network or policy failure while fetching source content."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FetchResponse:
    """One HTTP GET result (including 304 Not Modified)."""

    status_code: int
    url: str
    final_url: str
    body: bytes
    etag: str | None
    last_modified: str | None
    content_type: str | None
    not_modified: bool = False

    def text(self, encoding: str = "utf-8") -> str:
        """Decode body as text."""
        return self.body.decode(encoding)


class Fetcher(Protocol):
    """Injectable HTTP GET used by refresh (tests supply fixtures)."""

    def get(
        self,
        url: str,
        *,
        source_id: str | None,
        etag: str | None = None,
        max_bytes: int = MAX_RESPONSE_BYTES,
        content_kind: str = "json",
        timeout: int = DEFAULT_TIMEOUT_SEC,
    ) -> FetchResponse:
        """GET ``url`` honoring source allowlists."""
        ...


class _PolicyRedirectHandler(HTTPRedirectHandler):
    """Follow a bounded number of HTTPS redirects within the allowlist."""

    def __init__(self, *, source_id: str | None, max_redirects: int) -> None:
        super().__init__()
        self._source_id = source_id
        self._remaining = max_redirects

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if self._remaining <= 0:
            raise FetchError("redirects", f"exceeded {MAX_REDIRECTS} redirects")
        self._remaining -= 1
        parsed = urlparse(newurl)
        if parsed.scheme != "https":
            raise FetchError("scheme", f"redirect changed scheme to {parsed.scheme}")
        try:
            validate_fetch_url(newurl, source_id=self._source_id)
        except SourcePolicyError as exc:
            raise FetchError(exc.code, str(exc)) from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _header(headers: object, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _read_limited(response: object, max_bytes: int) -> bytes:
    length_header = _header(getattr(response, "headers", {}), "Content-Length")
    if length_header and length_header.isdigit() and int(length_header) > max_bytes:
        raise FetchError("oversized", f"Content-Length {length_header} exceeds {max_bytes}")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(65536)  # type: ignore[union-attr]
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FetchError("oversized", f"response exceeded {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


class SecureFetcher:
    """Production fetcher: HTTPS, allowlist, timeout, size cap, no code execution."""

    def get(
        self,
        url: str,
        *,
        source_id: str | None,
        etag: str | None = None,
        max_bytes: int = MAX_RESPONSE_BYTES,
        content_kind: str = "json",
        timeout: int = DEFAULT_TIMEOUT_SEC,
    ) -> FetchResponse:
        """GET ``url`` with scheduled or manual policy."""
        try:
            validated = validate_fetch_url(url, source_id=source_id)
        except SourcePolicyError as exc:
            raise FetchError(exc.code, str(exc)) from exc
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if etag:
            headers["If-None-Match"] = etag
        request = Request(validated, headers=headers, method="GET")
        opener = build_opener(
            _PolicyRedirectHandler(source_id=source_id, max_redirects=MAX_REDIRECTS)
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                body = _read_limited(response, max_bytes)
                content_type = _header(response.headers, "Content-Type")
                if not content_type_allowed(content_type, content_kind):
                    raise FetchError(
                        "content_type",
                        f"unexpected Content-Type {content_type!r} for {content_kind}",
                    )
                final_url = str(getattr(response, "url", validated))
                if final_url != validated:
                    try:
                        validate_fetch_url(final_url, source_id=source_id)
                    except SourcePolicyError as exc:
                        raise FetchError(exc.code, str(exc)) from exc
                return FetchResponse(
                    status_code=int(getattr(response, "status", 200)),
                    url=validated,
                    final_url=final_url,
                    body=body,
                    etag=_header(response.headers, "ETag"),
                    last_modified=_header(response.headers, "Last-Modified"),
                    content_type=content_type,
                )
        except FetchError:
            raise
        except HTTPError as exc:
            if exc.code == 304:
                return FetchResponse(
                    status_code=304,
                    url=validated,
                    final_url=validated,
                    body=b"",
                    etag=etag,
                    last_modified=None,
                    content_type=None,
                    not_modified=True,
                )
            raise FetchError("http", f"HTTP {exc.code} for {validated}") from exc
        except TimeoutError as exc:
            raise FetchError("timeout", f"timeout fetching {validated}") from exc
        except URLError as exc:
            raise FetchError("network", f"failed to fetch {validated}: {exc}") from exc


class MapFetcher:
    """Deterministic fetcher mapping URLs to bytes/errors (tests)."""

    def __init__(
        self,
        mapping: dict[str, FetchResponse | bytes | str | BaseException],
        *,
        prefix: bool = False,
    ) -> None:
        self._mapping = mapping
        self._prefix = prefix

    def get(
        self,
        url: str,
        *,
        source_id: str | None,
        etag: str | None = None,
        max_bytes: int = MAX_RESPONSE_BYTES,
        content_kind: str = "json",
        timeout: int = DEFAULT_TIMEOUT_SEC,
    ) -> FetchResponse:
        """Look up ``url`` in the fixture map after policy validation."""
        try:
            validated = validate_fetch_url(url, source_id=source_id)
        except SourcePolicyError as exc:
            raise FetchError(exc.code, str(exc)) from exc
        payload = self._mapping.get(validated)
        if payload is None and self._prefix:
            for key, value in self._mapping.items():
                if validated.startswith(key):
                    payload = value
                    break
        if payload is None:
            raise FetchError("missing", f"no fixture for {validated}")
        if isinstance(payload, BaseException):
            raise payload
        if isinstance(payload, FetchResponse):
            if payload.not_modified or payload.status_code == 304:
                return payload
            if len(payload.body) > max_bytes:
                raise FetchError("oversized", f"fixture exceeded {max_bytes} bytes")
            return payload
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        if len(raw) > max_bytes:
            raise FetchError("oversized", f"response exceeded {max_bytes} bytes")
        return FetchResponse(
            status_code=200,
            url=validated,
            final_url=validated,
            body=raw,
            etag=etag or '"fixture"',
            last_modified=None,
            content_type="text/plain",
        )


DEFAULT_FETCHER = SecureFetcher()
