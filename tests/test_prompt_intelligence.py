"""Prompt intelligence pipeline tests (deterministic fixtures, no live GitHub)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ylang.core.migrations import run_migrations
from ylang.importer.adapters.awesome_copilot import AwesomeCopilotAdapter
from ylang.importer.adapters.fabric import FabricPatternsAdapter
from ylang.importer.adapters.prompts_chat import PromptsChatAdapter
from ylang.importer.ingest import ingest_parsed_items
from ylang.importer.promote import PromotionError, promote_candidate, reject_candidate
from ylang.importer.refresh import (
    github_commits_url,
    github_license_url,
    github_tree_url,
    open_source_store,
    refresh_source,
)
from ylang.importer.risk import scan_prompt_risk
from ylang.importer.secure_fetch import FetchError, FetchResponse, MapFetcher
from ylang.importer.source_types import ParsedUpstreamItem, utcnow_iso
from ylang.library import open_library

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_CSV = FIXTURES / "sample_prompts.csv"
CC0 = (FIXTURES / "licenses" / "CC0.txt").read_text(encoding="utf-8")
MIT = (FIXTURES / "licenses" / "MIT.txt").read_text(encoding="utf-8")
COPILOT_PROMPT = (
    FIXTURES / "awesome_copilot" / "prompts" / "review-pr.prompt.md"
).read_text(encoding="utf-8")
FABRIC_PATTERN = (
    FIXTURES / "fabric" / "data" / "patterns" / "extract_wisdom" / "system.md"
).read_text(encoding="utf-8")
MALICIOUS = (FIXTURES / "malicious" / "exfiltrate.md").read_text(encoding="utf-8")

SHA = "abc123def456"


def _commit_json(sha: str = SHA) -> str:
    return json.dumps({"sha": sha})


def _tree(paths: list[str], *, truncated: bool = False) -> str:
    return json.dumps(
        {
            "truncated": truncated,
            "tree": [{"path": path, "type": "blob", "sha": "x"} for path in paths],
        }
    )


def _prompts_chat_fetcher(**overrides: object) -> MapFetcher:
    mapping: dict[str, FetchResponse | bytes | str | BaseException] = {
        github_commits_url("f", "prompts.chat"): _commit_json(),
        github_license_url("f", "prompts.chat", SHA): CC0,
        f"https://raw.githubusercontent.com/f/prompts.chat/{SHA}/prompts.csv": (
            SAMPLE_CSV.read_text(encoding="utf-8")
        ),
    }
    mapping.update(overrides)  # type: ignore[arg-type]
    return MapFetcher(mapping)


def test_offline_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("network disabled")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    library = open_library(tmp_path / "ylang.db")
    try:
        ids = {item.template_id for item in library.list(source="seed")}
        assert "summarize" in ids
        store = open_source_store(library)
        assert store.get_source("prompts-chat") is not None
    finally:
        library.close()


def test_migration_from_v0_6_preserves_templates(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE templates (
            template_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            latest_version INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            visibility TEXT NOT NULL DEFAULT 'private'
                CHECK (visibility IN ('public', 'private', 'archived')),
            tags_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE template_versions (
            template_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            body TEXT NOT NULL,
            params_json TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('seed', 'user', 'learned')),
            created_at TEXT NOT NULL,
            PRIMARY KEY (template_id, version)
        );
        """
    )
    now = utcnow_iso()
    connection.execute(
        "INSERT INTO templates VALUES ('keep-me', 'Keep', 1, ?, 'private', '[]')",
        (now,),
    )
    connection.execute(
        "INSERT INTO template_versions VALUES ('keep-me', 1, 'hello', '[]', 'user', ?)",
        (now,),
    )
    for version, name in (
        (1, "facts_workspace"),
        (2, "usage_improver_context_templates"),
        (3, "templates_fts"),
        (4, "usage_improver_outcome_metadata"),
        (5, "feedback_events"),
        (6, "prompt_experiments"),
        (7, "runtime_settings"),
        (8, "improver_cache"),
        (9, "apply_audit_log"),
        (10, "templates_visibility_archived"),
        (11, "usage_trace_columns"),
        (12, "usage_evaluation_json"),
        (13, "usage_trace_phase_b"),
    ):
        connection.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (version, name),
        )
    connection.commit()
    applied = run_migrations(connection)
    assert applied >= 1
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "prompt_sources" in tables
    assert "prompt_source_items" in tables
    assert "prompt_evaluation_snapshots" in tables
    assert "prompt_promotion_baselines" in tables
    assert "prompt_evaluation_runs" in tables
    assert "prompt_refresh_leases" in tables
    row = connection.execute(
        "SELECT name FROM templates WHERE template_id = 'keep-me'"
    ).fetchone()
    assert row is not None
    connection.close()


def test_first_import_and_unchanged_refresh(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    try:
        first = refresh_source(
            store, library, "prompts-chat", fetcher=_prompts_chat_fetcher()
        )
        assert first.status == "success"
        assert first.new == 3
        assert library.recall("character") is None
        second = refresh_source(
            store,
            library,
            "prompts-chat",
            fetcher=_prompts_chat_fetcher(
                **{
                    github_commits_url("f", "prompts.chat"): FetchResponse(
                        status_code=304,
                        url=github_commits_url("f", "prompts.chat"),
                        final_url=github_commits_url("f", "prompts.chat"),
                        body=b"",
                        etag='"etag"',
                        last_modified=None,
                        content_type="application/json",
                        not_modified=True,
                    )
                }
            ),
        )
        assert second.status == "unchanged"
        assert second.new == 0
    finally:
        library.close()


def test_changed_and_removed_upstream(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    adapter = PromptsChatAdapter()
    source = store.get_source("prompts-chat")
    assert source is not None
    try:
        items = adapter.parse(
            {"prompts.csv": SAMPLE_CSV.read_text(encoding="utf-8")},
            revision="sha-1",
        )
        ingest_parsed_items(
            store, library, source, items, revision="sha-1", mark_removed=True
        )
        promoted = promote_candidate(store, library, "prompts-chat:plain-role")
        changed_csv = SAMPLE_CSV.read_text(encoding="utf-8").replace(
            "You are a helpful writing assistant.",
            "You are a concise writing assistant.",
        )
        changed_csv = "\n".join(
            line
            for line in changed_csv.splitlines()
            if not line.startswith("Character,")
        )
        new_items = adapter.parse({"prompts.csv": changed_csv}, revision="sha-2")
        summary = ingest_parsed_items(
            store, library, source, new_items, revision="sha-2", mark_removed=True
        )
        assert summary.changed >= 1
        changed = store.get_item("prompts-chat:plain-role")
        assert changed is not None
        assert changed.candidate_state == "candidate_changed"
        assert changed.linked_template_id == promoted.template_id
        local = library.recall(promoted.template_id)
        assert local is not None
        assert "helpful writing assistant" in local.body
        removed = store.get_item("prompts-chat:character")
        assert removed is not None
        assert removed.candidate_state == "removed_upstream"
    finally:
        library.close()


def test_malformed_source_does_not_corrupt_library(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    try:
        before = {item.template_id for item in library.list()}
        fetcher = _prompts_chat_fetcher(
            **{github_commits_url("f", "prompts.chat"): "{not-json"}
        )
        summary = refresh_source(store, library, "prompts-chat", fetcher=fetcher)
        assert summary.status == "error"
        after = {item.template_id for item in library.list()}
        assert after == before
    finally:
        library.close()


def test_oversized_source_rejected(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    huge = FetchResponse(
        status_code=200,
        url=f"https://raw.githubusercontent.com/f/prompts.chat/{SHA}/prompts.csv",
        final_url=f"https://raw.githubusercontent.com/f/prompts.chat/{SHA}/prompts.csv",
        body=b"x" * 50,
        etag=None,
        last_modified=None,
        content_type="text/csv",
    )
    fetcher = _prompts_chat_fetcher(
        **{
            f"https://raw.githubusercontent.com/f/prompts.chat/{SHA}/prompts.csv": huge,
        }
    )
    original_get = fetcher.get

    def limited_get(url: str, **kwargs: object) -> FetchResponse:
        kwargs = dict(kwargs)
        if url.endswith("prompts.csv"):
            kwargs["max_bytes"] = 10
        return original_get(url, **kwargs)  # type: ignore[arg-type]

    fetcher.get = limited_get  # type: ignore[method-assign]
    try:
        summary = refresh_source(store, library, "prompts-chat", fetcher=fetcher)
        assert summary.status in {"error", "blocked"}
        assert library.recall("character") is None
    finally:
        library.close()


def test_redirect_to_unapproved_host() -> None:
    from ylang.importer.secure_fetch import _PolicyRedirectHandler
    from urllib.request import Request

    handler = _PolicyRedirectHandler(source_id="prompts-chat", max_redirects=3)
    req = Request("https://raw.githubusercontent.com/f/prompts.chat/main/prompts.csv")
    with pytest.raises(FetchError) as exc:
        handler.redirect_request(
            req, None, 302, "Found", {}, "https://evil.example/steal.csv"
        )
    assert exc.value.code in {"host", "prefix"}


def test_missing_license_blocks_scheduled_import(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    fetcher = _prompts_chat_fetcher(
        **{
            github_license_url("f", "prompts.chat", SHA): FetchError(
                "http", "HTTP 404"
            )
        }
    )
    try:
        summary = refresh_source(store, library, "prompts-chat", fetcher=fetcher)
        assert summary.status == "blocked"
        assert store.list_items(source_id="prompts-chat") == []
    finally:
        library.close()


def test_exact_duplicate_across_sources(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    source_a = store.get_source("prompts-chat")
    source_b = store.get_source("fabric-patterns")
    assert source_a is not None and source_b is not None
    body = "Summarize the following text clearly."
    item_a = ParsedUpstreamItem(
        upstream_item_id="one", title="Summarize", body=body
    )
    item_b = ParsedUpstreamItem(
        upstream_item_id="two", title="Summarize", body=body
    )
    try:
        ingest_parsed_items(
            store, library, source_a, [item_a], revision="a", mark_removed=False
        )
        ingest_parsed_items(
            store, library, source_b, [item_b], revision="b", mark_removed=False
        )
        second = store.get_item("fabric-patterns:two")
        assert second is not None
        assert second.duplicate_of_item_id == "prompts-chat:one"
    finally:
        library.close()


def test_risk_flags_and_high_risk_not_promotable(tmp_path: Path) -> None:
    report = scan_prompt_risk(MALICIOUS)
    assert report.level == "high"
    assert "reveal_secrets" in report.reasons
    assert "force_push_or_reset" in report.reasons
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    source = store.get_source("prompts-chat")
    assert source is not None
    try:
        ingest_parsed_items(
            store,
            library,
            source,
            [
                ParsedUpstreamItem(
                    upstream_item_id="evil",
                    title="Malicious",
                    body=MALICIOUS,
                )
            ],
            revision="x",
            mark_removed=False,
        )
        item = store.get_item("prompts-chat:evil")
        assert item is not None
        assert item.candidate_state == "quarantined"
        with pytest.raises(PromotionError, match="acknowledge-risk"):
            promote_candidate(store, library, item.item_id)
        assert library.recall("malicious") is None
        promoted = promote_candidate(
            store, library, item.item_id, acknowledge_risk=True
        )
        assert template_has_provenance(store, promoted.template_id)
    finally:
        library.close()


def template_has_provenance(store: object, template_id: str) -> bool:
    rows = store.provenance_for_template(template_id)  # type: ignore[union-attr]
    return bool(rows)


def test_rejected_prompt_does_not_resurface(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    source = store.get_source("prompts-chat")
    assert source is not None
    item = ParsedUpstreamItem(
        upstream_item_id="plain", title="Plain", body="You are a helpful writing assistant."
    )
    try:
        ingest_parsed_items(
            store, library, source, [item], revision="1", mark_removed=False
        )
        reject_candidate(store, "prompts-chat:plain")
        summary = ingest_parsed_items(
            store, library, source, [item], revision="2", mark_removed=False
        )
        assert summary.new == 0
        again = store.get_item("prompts-chat:plain")
        assert again is not None
        assert again.candidate_state == "rejected"
        listed = store.list_items(states=("candidate_new",))
        assert all(row.item_id != "prompts-chat:plain" for row in listed)
    finally:
        library.close()


def test_promotion_provenance(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    source = store.get_source("prompts-chat")
    assert source is not None
    try:
        items = PromptsChatAdapter().parse(
            {"prompts.csv": SAMPLE_CSV.read_text(encoding="utf-8")},
            revision="rev1",
        )
        ingest_parsed_items(
            store, library, source, items, revision="rev1", mark_removed=False
        )
        template = promote_candidate(store, library, "prompts-chat:character")
        assert template.source == "user"
        rows = store.provenance_for_template(template.template_id)
        assert rows[0].item_id == "prompts-chat:character"
        assert rows[0].upstream_revision == "rev1"
    finally:
        library.close()


def test_refresh_failure_ylang_remains_functional(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    fetcher = MapFetcher(
        {
            github_commits_url("f", "prompts.chat"): FetchError("network", "offline"),
        }
    )
    try:
        summary = refresh_source(store, library, "prompts-chat", fetcher=fetcher)
        assert summary.status == "error"
        assert library.list()
        store.ensure_builtin_sources()
    finally:
        library.close()


def test_awesome_copilot_prompt_files_only() -> None:
    adapter = AwesomeCopilotAdapter()
    files = {
        "prompts/review-pr.prompt.md": COPILOT_PROMPT,
        "agents/coder.agent.md": "should skip",
        "skills/foo.md": "skip",
    }
    selected = adapter.select_paths(list(files))
    assert selected == ["prompts/review-pr.prompt.md"]
    items = adapter.parse(files, revision=SHA)
    assert len(items) == 1
    assert items[0].metadata.get("tools") == ["search", "edit"]
    assert items[0].model_hint == "gpt-4.1"


def test_fabric_pattern_parse() -> None:
    adapter = FabricPatternsAdapter()
    path = "data/patterns/extract_wisdom/system.md"
    items = adapter.parse({path: FABRIC_PATTERN}, revision=SHA)
    assert len(items) == 1
    assert items[0].metadata["pattern"] == "extract_wisdom"


def test_copilot_refresh_ignores_agents(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    owner, repo = "github", "awesome-copilot"
    fetcher = MapFetcher(
        {
            github_commits_url(owner, repo): _commit_json(),
            github_license_url(owner, repo, SHA): MIT,
            github_tree_url(owner, repo, SHA): _tree(
                [
                    "prompts/review-pr.prompt.md",
                    "agents/coder.agent.md",
                    "skills/foo.skill.md",
                ]
            ),
            f"https://raw.githubusercontent.com/{owner}/{repo}/{SHA}/prompts/review-pr.prompt.md": COPILOT_PROMPT,
        }
    )
    try:
        summary = refresh_source(
            store, library, "github-awesome-copilot", fetcher=fetcher
        )
        assert summary.status == "success"
        assert summary.new == 1
        items = store.list_items(source_id="github-awesome-copilot")
        assert len(items) == 1
        assert "agents" not in items[0].upstream_item_id
    finally:
        library.close()


def test_manual_url_does_not_enable_scheduled_source(tmp_path: Path) -> None:
    from ylang.importer import import_prompts

    library = open_library(tmp_path / "db.sqlite")
    try:
        import_prompts(
            library,
            url="https://example.com/prompts.csv",
            csv_text=SAMPLE_CSV.read_text(encoding="utf-8"),
        )
        store = open_source_store(library)
        manual = store.get_source("manual-import")
        assert manual is not None
        assert manual.enabled is False
        catalog = store.get_source("prompts-chat")
        assert catalog is not None
        assert catalog.enabled is False
        assert store.list_items(source_id="manual-import")
    finally:
        library.close()


def test_copilot_accepts_github_and_prompts_prefixes() -> None:
    adapter = AwesomeCopilotAdapter()
    selected = adapter.select_paths(
        [
            ".github/prompts/review.prompt.md",
            "prompts/foo.prompt.md",
            "agents/skip.prompt.md",
            "README.md",
        ]
    )
    assert selected == [
        ".github/prompts/review.prompt.md",
        "prompts/foo.prompt.md",
    ]


def test_fabric_accepts_patterns_without_data_prefix() -> None:
    adapter = FabricPatternsAdapter()
    assert adapter.select_paths(["patterns/extract_wisdom/system.md"]) == [
        "patterns/extract_wisdom/system.md"
    ]


def test_empty_selected_tree_is_layout_error(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    owner, repo = "github", "awesome-copilot"
    fetcher = MapFetcher(
        {
            github_commits_url(owner, repo): _commit_json(),
            github_license_url(owner, repo, SHA): MIT,
            github_tree_url(owner, repo, SHA): _tree(["agents/coder.agent.md"]),
        }
    )
    try:
        summary = refresh_source(
            store, library, "github-awesome-copilot", fetcher=fetcher
        )
        assert summary.status == "blocked"
        assert summary.error is not None
        assert "source shape unexpected" in summary.error
    finally:
        library.close()


def test_evaluate_records_local_comparison_without_traffic(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from ylang.importer.evaluate import evaluate_candidate
    from ylang.usage.experiments import ExperimentStore
    from ylang.usage.store import UsageStore

    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    usage = UsageStore(library._connection)
    usage._ensure_schema()
    source = store.get_source("prompts-chat")
    assert source is not None
    try:
        items = PromptsChatAdapter().parse(
            {"prompts.csv": SAMPLE_CSV.read_text(encoding="utf-8")},
            revision="sha-eval",
        )
        ingest_parsed_items(
            store, library, source, items, revision="sha-eval", mark_removed=False
        )
        library.save(
            "character",
            name="Character",
            body="You are a character.",
            params=[],
            source="user",
            visibility="public",
        )
        now = datetime.now(timezone.utc)
        for index in range(3):
            usage.write_usage(
                surface="mcp",
                activity="improve:agent",
                model_used="test/model",
                prompt_tokens=10,
                cost=0.02,
                improver_fired=True,
                improver_accepted=index > 0,
                latency_ms=40,
                success=True,
                timestamp=now - timedelta(hours=index),
                improver_context_templates="character",
                improver_validated=True,
                improver_changed=True,
                cursor_mode="agent",
            )
        item = store.get_item("prompts-chat:character")
        assert item is not None
        report = evaluate_candidate(
            item,
            library,
            ExperimentStore(library._connection),
            usage,
            vs_template_id="character",
            fixture_input="write a haiku about rain",
            source_store=store,
        )
        assert report.candidate_variant.traffic_pct == 0.0
        assert report.candidate_variant.active is False
        assert report.current_template_id == "character"
        assert report.current_injections == 3
        assert report.current_accept_rate == pytest.approx(2 / 3)
        assert report.current_avg_cost == pytest.approx(0.02)
        assert report.body_diff_ratio is not None
        assert report.fixture_hash
        assert report.fixture_chars == len("write a haiku about rain")
        row = library._connection.execute(
            "SELECT experiment_id, current_injections FROM prompt_evaluation_snapshots WHERE item_id = ?",
            (item.item_id,),
        ).fetchone()
        assert row is not None
        assert row[1] == 3
    finally:
        library.close()


def test_promote_baseline_then_metrics_delta(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from ylang.importer.metrics import collect_metrics
    from ylang.usage.store import UsageStore

    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    usage = UsageStore(library._connection)
    usage._ensure_schema()
    source = store.get_source("prompts-chat")
    assert source is not None
    try:
        items = PromptsChatAdapter().parse(
            {"prompts.csv": SAMPLE_CSV.read_text(encoding="utf-8")},
            revision="sha-base",
        )
        ingest_parsed_items(
            store, library, source, items, revision="sha-base", mark_removed=False
        )
        library.save(
            "character",
            name="Character",
            body="old body",
            params=[],
            source="user",
            visibility="public",
        )
        now = datetime.now(timezone.utc)
        for index in range(3):
            usage.write_usage(
                surface="mcp",
                activity="improve:agent",
                model_used="test/model",
                prompt_tokens=10,
                cost=0.01,
                improver_fired=True,
                improver_accepted=False,
                latency_ms=80,
                success=True,
                timestamp=now - timedelta(hours=index + 3),
                improver_context_templates="character",
                improver_validated=True,
                improver_changed=True,
                cursor_mode="agent",
            )
        promoted = promote_candidate(
            store,
            library,
            "prompts-chat:character",
            template_id="character",
            usage_store=usage,
        )
        baselines = store.list_promotion_baselines()
        assert baselines
        assert baselines[0].template_id == promoted.template_id
        assert baselines[0].accept_rate == 0.0
        for _ in range(3):
            usage.write_usage(
                surface="mcp",
                activity="improve:agent",
                model_used="test/model",
                prompt_tokens=10,
                cost=0.01,
                improver_fired=True,
                improver_accepted=True,
                latency_ms=20,
                success=True,
                timestamp=datetime.now(timezone.utc),
                improver_context_templates="character",
                improver_validated=True,
                improver_changed=True,
                cursor_mode="agent",
                template_version=promoted.version,
            )
        from ylang.usage.aggregates import clear_aggregate_cache
        from ylang.importer.metrics import promoted_outcome_deltas

        clear_aggregate_cache()
        metrics = collect_metrics(store, usage, library=library)
        assert metrics.promoted_improved == 1
        assert metrics.promoted_regressed == 0
        deltas = promoted_outcome_deltas(store, library, usage)
        assert deltas[0].evidence_class == "observational"
        assert deltas[0].attribution == "versioned"
        assert deltas[0].status == "improved"
    finally:
        library.close()


def test_unversioned_post_promotion_stays_unknown(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from ylang.importer.metrics import promoted_outcome_deltas
    from ylang.usage.store import UsageStore

    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    usage = UsageStore(library._connection)
    usage._ensure_schema()
    source = store.get_source("prompts-chat")
    assert source is not None
    try:
        items = PromptsChatAdapter().parse(
            {"prompts.csv": SAMPLE_CSV.read_text(encoding="utf-8")},
            revision="sha-unk",
        )
        ingest_parsed_items(
            store, library, source, items, revision="sha-unk", mark_removed=False
        )
        library.save(
            "character",
            name="Character",
            body="old body",
            params=[],
            source="user",
            visibility="public",
        )
        now = datetime.now(timezone.utc)
        usage.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="test/model",
            prompt_tokens=10,
            cost=0.01,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=80,
            success=True,
            timestamp=now - timedelta(hours=1),
            improver_context_templates="character",
            improver_validated=True,
            improver_changed=True,
        )
        promoted = promote_candidate(
            store,
            library,
            "prompts-chat:character",
            template_id="character",
            usage_store=usage,
        )
        for _ in range(3):
            usage.write_usage(
                surface="mcp",
                activity="improve:agent",
                model_used="test/model",
                prompt_tokens=10,
                cost=0.01,
                improver_fired=True,
                improver_accepted=True,
                latency_ms=20,
                success=True,
                timestamp=datetime.now(timezone.utc),
                improver_context_templates="character",
                improver_validated=True,
                improver_changed=True,
            )
        deltas = promoted_outcome_deltas(store, library, usage)
        assert deltas
        assert deltas[0].status == "pending"
        assert deltas[0].attribution == "unknown"
        assert deltas[0].unversioned_events >= 1
        assert promoted.version >= 1
    finally:
        library.close()


def test_unknown_license_policy_blocks_scheduled_import(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    library._connection.execute(
        "UPDATE prompt_sources SET license_spdx = 'unknown' WHERE source_id = 'prompts-chat'"
    )
    library._connection.commit()
    try:
        summary = refresh_source(
            store, library, "prompts-chat", fetcher=_prompts_chat_fetcher()
        )
        assert summary.status == "blocked"
        assert summary.error is not None
        assert "license policy" in summary.error
        assert store.list_items(source_id="prompts-chat") == []
    finally:
        library.close()


def test_truncated_tree_does_not_mark_removed(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    owner, repo = "github", "awesome-copilot"
    good = MapFetcher(
        {
            github_commits_url(owner, repo): _commit_json(),
            github_license_url(owner, repo, SHA): MIT,
            github_tree_url(owner, repo, SHA): _tree(["prompts/review-pr.prompt.md"]),
            f"https://raw.githubusercontent.com/{owner}/{repo}/{SHA}/prompts/review-pr.prompt.md": COPILOT_PROMPT,
        }
    )
    try:
        first = refresh_source(
            store, library, "github-awesome-copilot", fetcher=good
        )
        assert first.status == "success"
        truncated = MapFetcher(
            {
                github_commits_url(owner, repo): _commit_json("deadbeef"),
                github_license_url(owner, repo, "deadbeef"): MIT,
                github_tree_url(owner, repo, "deadbeef"): _tree(
                    ["prompts/review-pr.prompt.md"], truncated=True
                ),
            }
        )
        summary = refresh_source(
            store, library, "github-awesome-copilot", fetcher=truncated
        )
        assert summary.status == "blocked"
        assert summary.error is not None
        assert "truncated" in summary.error
        remaining = store.list_items(source_id="github-awesome-copilot")
        assert remaining
        assert remaining[0].candidate_state != "removed_upstream"
        copilot = store.get_source("github-awesome-copilot")
        assert copilot is not None
        assert copilot.last_revision == SHA
    finally:
        library.close()


def test_partial_oversized_does_not_delete_last_known_good(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    owner, repo = "github", "awesome-copilot"
    good = MapFetcher(
        {
            github_commits_url(owner, repo): _commit_json(),
            github_license_url(owner, repo, SHA): MIT,
            github_tree_url(owner, repo, SHA): _tree(["prompts/review-pr.prompt.md"]),
            f"https://raw.githubusercontent.com/{owner}/{repo}/{SHA}/prompts/review-pr.prompt.md": COPILOT_PROMPT,
        }
    )
    try:
        first = refresh_source(
            store, library, "github-awesome-copilot", fetcher=good
        )
        assert first.status == "success"
        sha2 = "feedface"
        partial = MapFetcher(
            {
                github_commits_url(owner, repo): _commit_json(sha2),
                github_license_url(owner, repo, sha2): MIT,
                github_tree_url(owner, repo, sha2): _tree(
                    ["prompts/review-pr.prompt.md"]
                ),
                f"https://raw.githubusercontent.com/{owner}/{repo}/{sha2}/prompts/review-pr.prompt.md": FetchError(
                    "oversized", "too big"
                ),
            }
        )
        summary = refresh_source(
            store, library, "github-awesome-copilot", fetcher=partial
        )
        assert summary.status == "blocked"
        remaining = store.list_items(source_id="github-awesome-copilot")
        assert remaining[0].candidate_state != "removed_upstream"
        assert remaining[0].source_revision == SHA
    finally:
        library.close()


def test_cannot_enable_incompatible_copilot(tmp_path: Path) -> None:
    from ylang.importer.policy import SourcePolicyError

    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    try:
        source = store.get_source("github-awesome-copilot")
        assert source is not None
        assert source.compatibility_status == "incompatible"
        with pytest.raises(SourcePolicyError, match="prompt.md"):
            store.set_enabled("github-awesome-copilot", True)
        enabled = store.get_source("github-awesome-copilot")
        assert enabled is not None
        assert enabled.enabled is False
    finally:
        library.close()


def test_refresh_interval_skips_scheduled_source(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    try:
        first = refresh_source(
            store, library, "prompts-chat", fetcher=_prompts_chat_fetcher()
        )
        assert first.status == "success"
        store.set_enabled("prompts-chat", True)
        second = refresh_source(
            store,
            library,
            "prompts-chat",
            fetcher=_prompts_chat_fetcher(),
            require_enabled=True,
        )
        assert second.status == "skipped"
        assert second.error is not None
        assert "interval" in second.error
        forced = refresh_source(
            store,
            library,
            "prompts-chat",
            fetcher=_prompts_chat_fetcher(),
            require_enabled=True,
            force=True,
        )
        assert forced.status in {"success", "unchanged"}
    finally:
        library.close()


def test_execute_requires_authorization_and_budget(tmp_path: Path) -> None:
    from ylang.importer.evaluate import (
        EvaluationAuthorizationError,
        SimulatedCompleter,
        evaluate_candidate,
        execute_candidate_evaluation,
    )
    from ylang.usage.experiments import ExperimentStore

    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    source = store.get_source("prompts-chat")
    assert source is not None
    try:
        items = PromptsChatAdapter().parse(
            {"prompts.csv": SAMPLE_CSV.read_text(encoding="utf-8")},
            revision="sha-exec",
        )
        ingest_parsed_items(
            store, library, source, items, revision="sha-exec", mark_removed=False
        )
        library.save(
            "character",
            name="Character",
            body="You are a character.",
            params=[],
            source="user",
            visibility="public",
        )
        item = store.get_item("prompts-chat:character")
        assert item is not None
        inspect = evaluate_candidate(
            item,
            library,
            ExperimentStore(library._connection),
            vs_template_id="character",
            source_store=store,
        )
        assert inspect.mode == "inspect"
        assert inspect.evidence_class == "observational"
        with pytest.raises(EvaluationAuthorizationError, match="authorize-paid"):
            execute_candidate_evaluation(
                item,
                library,
                completer=SimulatedCompleter(),
                fixtures=["hello"],
                source_store=store,
                vs_template_id="character",
                authorize_paid=False,
                budget_usd=1.0,
                simulated=False,
            )
        run = execute_candidate_evaluation(
            item,
            library,
            completer=SimulatedCompleter(),
            fixtures=["hello"],
            source_store=store,
            vs_template_id="character",
            simulated=True,
        )
        assert run.mode == "execute"
        assert run.evidence_class == "simulated"
        assert run.cost_usd == 0.0
        assert run.baseline_output
        assert run.candidate_output
        payload = json.loads(run.evaluator_json)
        assert payload["quality_improvement_demonstrated"] is False
        assert payload["tools_granted"] is False
        assert store.list_evaluation_runs(item.item_id)
    finally:
        library.close()
