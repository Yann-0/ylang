"""Tests for console import helpers and data browser queries."""

from __future__ import annotations

from ylang.console.control_data import (
    StoreInventory,
    TemplateInventory,
    gather_effective_config,
    gather_store_inventory,
    gather_zero_accept_templates,
    improver_avg_latency_ms,
    should_show_facts_onboarding_cta,
    sort_by_priority,
)
from ylang.console.data_queries import domain_table_for_label, list_data_domains
from ylang.console.data_queries import db_stats, preview_table
from ylang.console.data_mutators import delete_usage_row, purge_usage_older_than
from ylang.console.import_ops import import_json_payload
from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.core.stores import open_stores
from ylang.settings import Settings
from ylang.usage.improver_analytics import ImproverFunnelSummary, TemplateEffectivenessRow


def test_gather_control_data(tmp_path) -> None:
    stores = open_stores(tmp_path / "ylang.db")
    try:
        stores.library.save(
            "ctrl-test",
            name="Ctrl Test",
            body="Hello",
            params=[],
            source="user",
            visibility="public",
        )
        stores.memory.remember("prefers tests", "private", workspace="ylang")
        runtime = RuntimeSettingsStore(stores.store._connection)
        runtime.set("models_improve", "mistral/mistral-small-latest")
        inventory = gather_store_inventory(
            stores.library,
            stores.memory,
            stores.store._connection,
        )
        assert inventory.templates.total >= 1
        assert inventory.facts_total >= 1
        config = gather_effective_config(Settings(), runtime)
        assert "mistral" in config.models_improve
    finally:
        stores.close()


def test_data_browser_search_filter(tmp_path) -> None:
    stores = open_stores(tmp_path / "ylang.db")
    try:
        stores.store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="openai/gpt-4o",
            prompt_tokens=5,
            cost=0.0,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=10,
            success=True,
        )
        preview = preview_table(
            stores.store._connection,
            "usage",
            limit=5,
            offset=0,
            search="improve",
        )
        assert preview is not None
        assert preview.total_count >= 1
        preview_miss = preview_table(
            stores.store._connection,
            "usage",
            limit=5,
            offset=0,
            search="zzzznotfound",
        )
        assert preview_miss is not None
        assert preview_miss.total_count == 0
    finally:
        stores.close()


def test_usage_mutators(tmp_path) -> None:
    stores = open_stores(tmp_path / "ylang.db")
    try:
        stores.store.write_usage(
            surface="mcp",
            activity="code",
            model_used="openai/gpt-4o",
            prompt_tokens=1,
            cost=0.0,
            improver_fired=False,
            improver_accepted=False,
            latency_ms=1,
            success=True,
        )
        row = stores.store._connection.execute(
            "SELECT id FROM usage ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert delete_usage_row(stores.store._connection, int(row[0]))
        assert purge_usage_older_than(stores.store._connection, 3650) == 0
    finally:
        stores.close()


def test_import_json_payload_roundtrip(tmp_path) -> None:
    stores = open_stores(tmp_path / "ylang.db")
    try:
        payload = {
            "version": 1,
            "templates": [
                {
                    "template_id": "import-test",
                    "name": "Import Test",
                    "body": "Do {task}",
                    "params": [{"name": "task", "description": "Task"}],
                    "source": "user",
                    "visibility": "private",
                    "tags": [],
                }
            ],
            "facts": [
                {"fact": "likes tests", "scope": "private", "workspace": "ylang"},
            ],
        }
        templates, facts = import_json_payload(stores.library, stores.memory, payload)
        assert templates == 1
        assert facts == 1
        recalled = stores.library.recall("import-test")
        assert recalled is not None
        assert recalled.body == "Do {task}"
    finally:
        stores.close()


def test_data_browser_preview(tmp_path) -> None:
    stores = open_stores(tmp_path / "ylang.db")
    try:
        stats = db_stats(stores.store._connection)
        assert "usage" in stats
        preview = preview_table(stores.store._connection, "usage", limit=5, offset=0)
        assert preview is not None
        assert preview.table_name == "usage"
    finally:
        stores.close()


def test_list_data_domains_and_resolve_label() -> None:
    domains = list_data_domains()
    labels = [label for label, _table in domains]
    assert "Usage" in labels
    assert "Audit" in labels
    assert domain_table_for_label("cache") == "improver_cache"
    assert domain_table_for_label("unknown") is None


def test_improver_avg_latency_ms() -> None:
    from ylang.usage.improver_analytics import ImproverModeStats

    funnel = ImproverFunnelSummary(
        total_fired=0,
        total_validated=0,
        total_changed=0,
        total_accepted=0,
        validation_rate=0.0,
        change_rate=0.0,
        accept_rate=0.0,
        by_mode={},
        top_rejection_reasons={},
    )
    assert improver_avg_latency_ms(funnel) is None
    funnel = ImproverFunnelSummary(
        total_fired=10,
        total_validated=8,
        total_changed=7,
        total_accepted=6,
        validation_rate=0.8,
        change_rate=0.7,
        accept_rate=0.6,
        by_mode={
            "agent": ImproverModeStats(
                mode="agent",
                fired=4,
                validated=3,
                changed=3,
                accepted=2,
                avg_latency_ms=100.0,
                avg_cost=0.01,
                top_rejection_reasons={},
            ),
            "plan": ImproverModeStats(
                mode="plan",
                fired=6,
                validated=5,
                changed=4,
                accepted=4,
                avg_latency_ms=200.0,
                avg_cost=0.02,
                top_rejection_reasons={},
            ),
        },
        top_rejection_reasons={},
    )
    assert improver_avg_latency_ms(funnel) == 160.0


def test_gather_zero_accept_templates() -> None:
    rows = [
        TemplateEffectivenessRow(
            template_id="good",
            injections=5,
            accepted=3,
            validated=4,
            accept_rate=0.6,
            avg_cost=0.01,
            avg_latency_ms=50.0,
        ),
        TemplateEffectivenessRow(
            template_id="toxic",
            injections=4,
            accepted=0,
            validated=1,
            accept_rate=0.0,
            avg_cost=0.02,
            avg_latency_ms=80.0,
        ),
        TemplateEffectivenessRow(
            template_id="low-sample",
            injections=2,
            accepted=0,
            validated=0,
            accept_rate=0.0,
            avg_cost=0.0,
            avg_latency_ms=10.0,
        ),
    ]
    toxic = gather_zero_accept_templates(rows)
    assert len(toxic) == 1
    assert toxic[0].template_id == "toxic"


def test_should_show_facts_onboarding_cta() -> None:
    sparse = StoreInventory(
        templates=TemplateInventory(total=0, public=0, private=0, by_source={}, archived=0),
        facts_total=2,
        facts_by_scope={"private": 2},
        facts_by_workspace={"(global)": 2},
        usage_rows=0,
    )
    assert should_show_facts_onboarding_cta(sparse) is True

    enough_total = StoreInventory(
        templates=TemplateInventory(total=0, public=0, private=0, by_source={}, archived=0),
        facts_total=5,
        facts_by_scope={"private": 5},
        facts_by_workspace={"(global)": 3, "ylang": 3},
        usage_rows=0,
    )
    assert should_show_facts_onboarding_cta(enough_total) is False

    sparse_workspace = StoreInventory(
        templates=TemplateInventory(total=0, public=0, private=0, by_source={}, archived=0),
        facts_total=4,
        facts_by_scope={"private": 4},
        facts_by_workspace={"(global)": 3, "ylang": 1},
        usage_rows=0,
    )
    assert should_show_facts_onboarding_cta(sparse_workspace) is True


def test_sort_by_priority() -> None:
    from dataclasses import dataclass

    @dataclass
    class _Row:
        priority: str
        label: str

    rows = [
        _Row("low", "c"),
        _Row("high", "a"),
        _Row("medium", "b"),
    ]
    ordered = sort_by_priority(rows)
    assert [row.label for row in ordered] == ["a", "b", "c"]
