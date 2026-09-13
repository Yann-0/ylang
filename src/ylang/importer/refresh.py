"""Refresh pipeline: fetch → parse → provenance → candidate. Idempotent."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ylang.importer.adapters.awesome_copilot import AwesomeCopilotAdapter, awesome_copilot_raw_url
from ylang.importer.adapters.fabric import FabricPatternsAdapter, fabric_raw_url
from ylang.importer.adapters.prompts_chat import (
    PROMPTS_CHAT_CSV_NAME,
    PROMPTS_CHAT_OWNER_REPOS,
    PromptsChatAdapter,
    prompts_chat_raw_csv_url,
)
from ylang.importer.ingest import ingest_parsed_items
from ylang.importer.policy import (
    MAX_FILE_BYTES,
    MAX_INGEST_ITEMS,
    MAX_RESPONSE_BYTES,
    MAX_TREE_BYTES,
    REFRESH_LEASE_TTL_SEC,
    SourcePolicyError,
    is_scheduled_source,
    license_policy_error,
    license_text_matches,
    scheduled_license_required,
)
from ylang.importer.secure_fetch import DEFAULT_FETCHER, FetchError, Fetcher
from ylang.importer.source_store import PromptSourceStore, source_store_from_connection
from ylang.importer.source_types import (
    MANUAL_SOURCE_ID,
    ParsedUpstreamItem,
    PromptSource,
    RefreshSummary,
)

if TYPE_CHECKING:
    from ylang.library.store import Library

_ADAPTERS = {
    "prompts-chat": PromptsChatAdapter(),
    "github-awesome-copilot": AwesomeCopilotAdapter(),
    "fabric-patterns": FabricPatternsAdapter(),
}

_REPO = {
    "prompts-chat": ("f", "prompts.chat"),
    "github-awesome-copilot": ("github", "awesome-copilot"),
    "fabric-patterns": ("danielmiessler", "Fabric"),
}

_LOCKS_GUARD = threading.Lock()
_SOURCE_LOCKS: dict[str, threading.Lock] = {}


def _lock_for(source_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _SOURCE_LOCKS.setdefault(source_id, threading.Lock())


def github_commits_url(owner: str, repo: str, ref: str = "main") -> str:
    """GitHub commits API URL used for revision / ETag checks."""
    return f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}"


def github_tree_url(owner: str, repo: str, sha: str) -> str:
    """Recursive git tree URL."""
    return f"https://api.github.com/repos/{owner}/{repo}/git/trees/{sha}?recursive=1"


def github_license_url(owner: str, repo: str, revision: str) -> str:
    """Raw LICENSE URL at a revision."""
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{revision}/LICENSE"


def _parse_sha(payload: bytes) -> str:
    data = json.loads(payload.decode("utf-8"))
    if isinstance(data, dict) and data.get("sha"):
        return str(data["sha"])
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0]["sha"])
    msg = "malformed GitHub commit payload"
    raise ValueError(msg)


def parse_github_tree(payload: bytes) -> tuple[list[str], bool]:
    """Return blob paths and whether GitHub truncated the tree listing."""
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        msg = "malformed GitHub tree payload"
        raise ValueError(msg)
    truncated = bool(data.get("truncated"))
    tree = data.get("tree")
    if not isinstance(tree, list):
        msg = "malformed GitHub tree payload"
        raise ValueError(msg)
    paths: list[str] = []
    for node in tree:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "blob":
            continue
        path = node.get("path")
        if isinstance(path, str):
            paths.append(path)
    return paths, truncated


def _parse_tree_paths(payload: bytes) -> list[str]:
    paths, truncated = parse_github_tree(payload)
    if truncated:
        raise SourcePolicyError(
            "truncated",
            "git tree listing is truncated; refusing incomplete ingest",
        )
    return paths


def _check_license(fetcher: Fetcher, source: PromptSource, revision: str) -> None:
    policy_error = license_policy_error(source)
    if policy_error:
        raise SourcePolicyError("license", policy_error)
    if not scheduled_license_required(source):
        return
    owner, repo = _REPO[source.source_id]
    url = github_license_url(owner, repo, revision)
    try:
        response = fetcher.get(
            url,
            source_id=source.source_id,
            max_bytes=MAX_FILE_BYTES,
            content_kind="license",
        )
    except FetchError as exc:
        raise SourcePolicyError("license", f"license fetch failed: {exc}") from exc
    if not license_text_matches(response.text(), source.license_spdx):
        raise SourcePolicyError(
            "license",
            f"license text does not match policy {source.license_spdx}",
        )


def _fetch_revision(
    fetcher: Fetcher,
    source: PromptSource,
) -> tuple[str, str | None, bool]:
    owner, repo = _REPO[source.source_id]
    url = github_commits_url(owner, repo)
    response = fetcher.get(
        url,
        source_id=source.source_id,
        etag=source.last_etag,
        max_bytes=MAX_FILE_BYTES,
        content_kind="json",
    )
    if response.not_modified and source.last_revision:
        return source.last_revision, response.etag or source.last_etag, True
    sha = _parse_sha(response.body)
    unchanged = bool(source.last_revision and source.last_revision == sha)
    return sha, response.etag, unchanged


def _fetch_prompts_chat_files(
    fetcher: Fetcher,
    source: PromptSource,
    revision: str,
) -> dict[str, str]:
    errors: list[str] = []
    for owner, repo in PROMPTS_CHAT_OWNER_REPOS:
        url = prompts_chat_raw_csv_url(owner, repo, revision)
        try:
            response = fetcher.get(
                url,
                source_id=source.source_id,
                max_bytes=MAX_RESPONSE_BYTES,
                content_kind="csv",
            )
            return {PROMPTS_CHAT_CSV_NAME: response.text()}
        except FetchError as exc:
            errors.append(str(exc))
    raise FetchError("http", "; ".join(errors) or "prompts.csv missing")


def _fetch_tree_files(
    fetcher: Fetcher,
    source: PromptSource,
    revision: str,
    adapter: AwesomeCopilotAdapter | FabricPatternsAdapter,
) -> dict[str, str]:
    owner, repo = _REPO[source.source_id]
    tree = fetcher.get(
        github_tree_url(owner, repo, revision),
        source_id=source.source_id,
        max_bytes=MAX_TREE_BYTES,
        content_kind="json",
    )
    tree_paths = _parse_tree_paths(tree.body)
    if not tree_paths:
        raise SourcePolicyError(
            "layout",
            f"empty git tree for {source.source_id}",
        )
    paths = adapter.select_paths(tree_paths)
    if not paths:
        hint = getattr(adapter, "layout_hint", "expected source files")
        raise SourcePolicyError(
            "layout",
            f"source shape unexpected: 0 files matched for {source.source_id} "
            f"({len(tree_paths)} blobs). Expected: {hint}",
        )
    files: dict[str, str] = {}
    raw_url = awesome_copilot_raw_url if source.source_id == "github-awesome-copilot" else fabric_raw_url
    for path in paths:
        url = raw_url(revision, path)
        try:
            response = fetcher.get(
                url,
                source_id=source.source_id,
                max_bytes=MAX_FILE_BYTES,
                content_kind="markdown",
            )
        except FetchError as exc:
            raise SourcePolicyError(
                "partial",
                f"incomplete fetch for {path}: {exc}; last-known-good preserved",
            ) from exc
        files[path] = response.text()
    if len(files) != len(paths):
        raise SourcePolicyError(
            "partial",
            "incomplete tree download; last-known-good preserved",
        )
    return files


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def refresh_interval_remaining(source: PromptSource, *, now: datetime | None = None) -> float | None:
    """Hours remaining before the next scheduled refresh is due, or None if due."""
    if source.refresh_interval_hours <= 0 or not source.last_success_at:
        return None
    anchor = now or datetime.now(timezone.utc)
    last = _parse_iso(source.last_success_at)
    elapsed = (anchor - last).total_seconds() / 3600.0
    remaining = source.refresh_interval_hours - elapsed
    if remaining <= 0:
        return None
    return remaining


def refresh_source(
    store: PromptSourceStore,
    library: Library,
    source_id: str,
    *,
    fetcher: Fetcher | None = None,
    parsed_items: list[ParsedUpstreamItem] | None = None,
    revision: str | None = None,
    mark_removed: bool = True,
    require_enabled: bool = False,
    force: bool = False,
) -> RefreshSummary:
    """Refresh one source into candidate quarantine. Never writes active templates."""
    lock = _lock_for(source_id)
    if not lock.acquire(blocking=False):
        return RefreshSummary(
            source_id=source_id,
            status="blocked",
            revision_before=None,
            revision_after=None,
            error="refresh already in progress",
        )
    owner = f"{os.getpid()}-{threading.get_ident()}-{source_id}"
    leased = False
    try:
        source = store.get_source(source_id)
        if source is None:
            return RefreshSummary(
                source_id=source_id,
                status="error",
                revision_before=None,
                revision_after=None,
                error=f"unknown source: {source_id}",
            )
        if require_enabled and not source.enabled:
            return RefreshSummary(
                source_id=source_id,
                status="unchanged",
                revision_before=source.last_revision,
                revision_after=source.last_revision,
                error="source disabled",
            )
        if require_enabled and not is_scheduled_source(source):
            return RefreshSummary(
                source_id=source_id,
                status="unchanged",
                revision_before=source.last_revision,
                revision_after=source.last_revision,
                error="manual sources are never scheduled",
            )
        if require_enabled and not force:
            remaining = refresh_interval_remaining(source)
            if remaining is not None:
                return RefreshSummary(
                    source_id=source_id,
                    status="skipped",
                    revision_before=source.last_revision,
                    revision_after=source.last_revision,
                    error=f"refresh interval not elapsed ({remaining:.1f}h remaining)",
                )
        if require_enabled and source.compatibility_status == "incompatible":
            return RefreshSummary(
                source_id=source_id,
                status="blocked",
                revision_before=source.last_revision,
                revision_after=source.last_revision,
                error=source.compatibility_note
                or "source incompatible with v1 prompt adapter",
            )
        if not store.try_acquire_refresh_lease(
            source_id, owner=owner, ttl_sec=REFRESH_LEASE_TTL_SEC
        ):
            return RefreshSummary(
                source_id=source_id,
                status="blocked",
                revision_before=source.last_revision,
                revision_after=source.last_revision,
                error="refresh already in progress",
            )
        leased = True
        return _refresh_source_locked(
            store,
            library,
            source,
            fetcher=fetcher,
            parsed_items=parsed_items,
            revision=revision,
            mark_removed=mark_removed,
        )
    finally:
        if leased:
            store.release_refresh_lease(source_id, owner=owner)
        lock.release()


def _refresh_source_locked(
    store: PromptSourceStore,
    library: Library,
    source: PromptSource,
    *,
    fetcher: Fetcher | None,
    parsed_items: list[ParsedUpstreamItem] | None,
    revision: str | None,
    mark_removed: bool,
) -> RefreshSummary:
    active_fetcher = fetcher or DEFAULT_FETCHER
    source_id = source.source_id
    store.mark_attempt(source_id)
    source = store.get_source(source_id) or source

    try:
        if parsed_items is not None:
            if len(parsed_items) > MAX_INGEST_ITEMS:
                raise SourcePolicyError(
                    "budget",
                    f"item count {len(parsed_items)} exceeds {MAX_INGEST_ITEMS}",
                )
            rev = revision or content_revision_from_items(parsed_items)
            _check_license_if_needed(active_fetcher, source, rev)
            summary = ingest_parsed_items(
                store,
                library,
                source,
                parsed_items,
                revision=rev,
                mark_removed=mark_removed,
            )
            store.mark_success(source_id, revision=rev, etag=source.last_etag)
            store.record_run(summary)
            return summary

        if source.adapter == "csv-manual":
            raise SourcePolicyError(
                "source",
                "manual CSV import is not a scheduled source",
            )
        if source.adapter not in _ADAPTERS:
            raise SourcePolicyError("adapter", f"unknown adapter {source.adapter}")

        sha, etag, unchanged = _fetch_revision(active_fetcher, source)
        if unchanged:
            store.mark_success(source_id, revision=sha, etag=etag)
            summary = RefreshSummary(
                source_id=source_id,
                status="unchanged",
                revision_before=source.last_revision,
                revision_after=sha,
            )
            store.record_run(summary)
            return summary

        _check_license(active_fetcher, source, sha)
        adapter = _ADAPTERS[source.adapter]
        if source.adapter == "prompts-chat":
            files = _fetch_prompts_chat_files(active_fetcher, source, sha)
        else:
            files = _fetch_tree_files(active_fetcher, source, sha, adapter)  # type: ignore[arg-type]
        items = adapter.parse(files, revision=sha)
        if len(items) > MAX_INGEST_ITEMS:
            raise SourcePolicyError(
                "budget",
                f"item count {len(items)} exceeds {MAX_INGEST_ITEMS}",
            )
        if not items:
            hint = getattr(adapter, "layout_hint", "expected source files")
            note = (
                f"source shape unexpected: 0 parsed items for {source_id} "
                f"({len(files)} files). Expected: {hint}. "
                "Refusing to convert agents/skills/tools into ordinary prompts."
            )
            store.set_compatibility(source_id, "incompatible", note, disable=True)
            raise SourcePolicyError("layout", note)
        store.set_compatibility(source_id, "eligible", None)
        summary = ingest_parsed_items(
            store,
            library,
            source,
            items,
            revision=sha,
            mark_removed=mark_removed,
        )
        store.mark_success(source_id, revision=sha, etag=etag)
        store.record_run(summary)
        return summary
    except (FetchError, SourcePolicyError, ValueError, OSError, json.JSONDecodeError) as exc:
        store.mark_error(source_id, str(exc))
        if isinstance(exc, SourcePolicyError) and exc.code in {"layout", "truncated"}:
            store.set_compatibility(
                source_id,
                "incompatible",
                str(exc),
                disable=True,
            )
        summary = RefreshSummary(
            source_id=source_id,
            status="blocked" if isinstance(exc, SourcePolicyError) else "error",
            revision_before=source.last_revision,
            revision_after=source.last_revision,
            error=str(exc),
        )
        store.record_run(summary)
        return summary


def _check_license_if_needed(
    fetcher: Fetcher, source: PromptSource, revision: str
) -> None:
    if source.source_id == MANUAL_SOURCE_ID:
        return
    if revision.startswith("fixture:") or revision.startswith("sha256:"):
        return
    _check_license(fetcher, source, revision)


def content_revision_from_items(items: list[ParsedUpstreamItem]) -> str:
    """Stable revision when ingesting a local/manual payload."""
    from ylang.importer.normalize import sha256_text

    blob = "\n".join(f"{item.upstream_item_id}\n{item.body}" for item in items)
    return f"sha256:{sha256_text(blob)}"


def refresh_all_enabled(
    store: PromptSourceStore,
    library: Library,
    *,
    fetcher: Fetcher | None = None,
    force: bool = False,
) -> list[RefreshSummary]:
    """Refresh sources with ``enabled=1``. Manual-import is never included."""
    summaries: list[RefreshSummary] = []
    for source in store.list_sources():
        if not source.enabled or not is_scheduled_source(source):
            continue
        summaries.append(
            refresh_source(
                store,
                library,
                source.source_id,
                fetcher=fetcher,
                require_enabled=True,
                force=force,
            )
        )
    return summaries


def open_source_store(library: Library) -> PromptSourceStore:
    """Source store on the library's shared SQLite connection."""
    return source_store_from_connection(library._connection)
