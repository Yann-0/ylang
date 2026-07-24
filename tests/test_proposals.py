"""Tests for governed proposal apply flow."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from ylang.console import register_console_routes
from ylang.console.apply_audit import ApplyAuditStore
from ylang.console.proposals import apply_proposal, collect_pending_proposals
from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.gateway.routes import register_gateway_routes
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.mcp.deps import YlangDeps
from ylang.settings import ProviderKeys, Settings
from ylang.usage.experiments import ExperimentStore
from ylang.usage.store import UsageWindow
from datetime import datetime, timedelta, timezone

from ylang.usage.aggregates import clear_aggregate_cache

_AUTH_HEADERS = {"Authorization": "Bearer secret-token"}


def _wide_window() -> UsageWindow:
    now = datetime.now(timezone.utc)
    return UsageWindow(since=now - timedelta(days=7), until=now + timedelta(hours=1))


@pytest.fixture
def proposals_client(
    ylang_deps: YlangDeps, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setenv("YLANG_AUTH_TOKEN", "secret-token")
    settings = Settings(transport="http", auth_token="secret-token")
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(),
    )
    engine = Engine(ylang_deps.store, surface="gateway", router=router)
    server = FastMCP("ylang-proposals-test", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    register_console_routes(server, ylang_deps, settings, gateway_engine=engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), "secret-token")
    return TestClient(app)


def test_proposals_page_renders(proposals_client: TestClient) -> None:
    response = proposals_client.get("/console/proposals", headers=_AUTH_HEADERS)
    assert response.status_code == 200
    assert "Pending proposals" in response.text
    assert "Nothing is auto-applied" in response.text


def test_apply_suggest_facts_redirect(ylang_deps: YlangDeps) -> None:
    from ylang.console.proposals import (
        APPLY_SUGGEST_FACTS,
        apply_proposal,
        proposal_redirect_after_apply,
    )

    store = ylang_deps.store
    runtime = RuntimeSettingsStore(store._connection)
    audit = ApplyAuditStore(store._connection)
    detail = apply_proposal(
        "action:suggest-facts",
        store=store,
        library=ylang_deps.library,
        connection=store._connection,
        runtime_store=runtime,
        audit_store=audit,
        window=_wide_window(),
    )
    assert "fact suggestion" in detail.lower()
    assert proposal_redirect_after_apply("action:suggest-facts") == "/console/facts?suggest=1"
    assert audit.recent(limit=1)[0].action_type == APPLY_SUGGEST_FACTS


def test_apply_archive_unused_proposal(ylang_deps: YlangDeps) -> None:
    library = ylang_deps.library
    library.save(
        "archive-me",
        name="Archive Me",
        body="unused public",
        params=[],
        source="user",
        visibility="public",
    )
    store = ylang_deps.store
    runtime = RuntimeSettingsStore(store._connection)
    audit = ApplyAuditStore(store._connection)
    detail = apply_proposal(
        "action:archive-unused:archive-me",
        store=store,
        library=library,
        connection=store._connection,
        runtime_store=runtime,
        audit_store=audit,
        window=_wide_window(),
    )
    assert "archived" in detail
    recalled = library.recall("archive-me")
    assert recalled is not None
    assert recalled.visibility == "archived"


def test_collect_control_proposals_includes_suggest_facts(ylang_deps: YlangDeps) -> None:
    from ylang.console.proposals import collect_control_proposals

    proposals = collect_control_proposals(
        ylang_deps.store,
        ylang_deps.library,
        ylang_deps.store._connection,
        _wide_window(),
    )
    assert any(item.proposal_id == "action:suggest-facts" for item in proposals)


def test_collect_control_proposals_includes_archive_toxic(
    ylang_deps: YlangDeps,
) -> None:
    from datetime import datetime, timezone

    from ylang.console.proposals import collect_control_proposals

    library = ylang_deps.library
    library.save(
        "toxic-ctrl",
        name="Toxic Ctrl",
        body="toxic body",
        params=[],
        source="user",
        visibility="private",
    )
    store = ylang_deps.store
    for _ in range(3):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="test/model",
            prompt_tokens=10,
            cost=0.0,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=1,
            success=True,
            timestamp=datetime.now(timezone.utc),
            improver_context_templates="toxic-ctrl",
            improver_validated=True,
            improver_changed=True,
        )

    proposals = collect_control_proposals(
        store,
        library,
        store._connection,
        _wide_window(),
    )
    toxic = next(
        item for item in proposals if item.proposal_id.startswith("action:archive-toxic:")
    )
    assert "toxic-ctrl" in (toxic.template_id or "")
    assert toxic.apply_type == "archive_templates"


def test_apply_runtime_setting_proposal(ylang_deps: YlangDeps) -> None:
    store = ylang_deps.store
    runtime = RuntimeSettingsStore(store._connection)
    audit = ApplyAuditStore(store._connection)
    clear_aggregate_cache()

    for _ in range(6):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="openai/gpt-4o",
            prompt_tokens=10,
            cost=0.01,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=100,
            success=True,
            improver_validated=True,
            improver_changed=True,
        )

    window = _wide_window()
    runtime.set("learned_template_limit", "1")
    proposals_matched = collect_pending_proposals(store, store._connection, window)
    assert all(
        item.proposal_id != "suggestion:improver-accept-rate-low"
        for item in proposals_matched
    )
    runtime.delete("learned_template_limit")

    proposals = collect_pending_proposals(store, store._connection, window)
    low_accept = next(
        item for item in proposals if item.proposal_id == "suggestion:improver-accept-rate-low"
    )
    assert low_accept.apply_type == "runtime_setting"
    assert low_accept.setting_key == "learned_template_limit"
    assert low_accept.setting_value == "1"

    detail = apply_proposal(
        "suggestion:improver-accept-rate-low",
        store=store,
        library=ylang_deps.library,
        connection=store._connection,
        runtime_store=runtime,
        audit_store=audit,
        window=window,
    )
    assert "learned_template_limit=1" in detail
    assert runtime.get("learned_template_limit") == "1"
    entries = audit.recent(limit=1)
    assert entries[0].proposal_id == "suggestion:improver-accept-rate-low"


def test_apply_experiment_winner(ylang_deps: YlangDeps) -> None:
    store = ylang_deps.store
    runtime = RuntimeSettingsStore(store._connection)
    audit = ApplyAuditStore(store._connection)
    clear_aggregate_cache()
    experiments = ExperimentStore(store._connection)
    experiments.upsert_variant(
        experiment_id="improver-agent",
        variant_id="control",
        config_hash="control",
        traffic_pct=50,
        active=True,
    )
    experiments.upsert_variant(
        experiment_id="improver-agent",
        variant_id="variant-a",
        config_hash="concise",
        traffic_pct=50,
        active=False,
    )
    for accepted, variant in (
        (True, "control"),
        (True, "control"),
        (True, "control"),
        (True, "control"),
        (True, "control"),
        (False, "variant-a"),
        (False, "variant-a"),
        (False, "variant-a"),
        (False, "variant-a"),
        (False, "variant-a"),
    ):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="openai/gpt-4o",
            prompt_tokens=10,
            cost=0.01,
            improver_fired=True,
            improver_accepted=accepted,
            latency_ms=100,
            success=True,
            experiment_variant=variant,
        )

    window = _wide_window()
    proposals = collect_pending_proposals(store, store._connection, window)
    assert any(
        item.proposal_id == "experiment:improver-agent:control" for item in proposals
    )
    apply_proposal(
        "experiment:improver-agent:control",
        store=store,
        library=ylang_deps.library,
        connection=store._connection,
        runtime_store=runtime,
        audit_store=audit,
        window=window,
    )
    active = experiments.list_active("improver-agent")
    assert len(active) == 1
    assert active[0].variant_id == "control"


def test_apply_direct_setting_proposal(ylang_deps: YlangDeps) -> None:
    store = ylang_deps.store
    runtime = RuntimeSettingsStore(store._connection)
    audit = ApplyAuditStore(store._connection)
    detail = apply_proposal(
        "setting:learned_template_limit=3",
        store=store,
        library=ylang_deps.library,
        connection=store._connection,
        runtime_store=runtime,
        audit_store=audit,
        window=_wide_window(),
    )
    assert detail == "set runtime setting learned_template_limit=3"
    assert runtime.get("learned_template_limit") == "3"
    assert audit.recent(limit=1)[0].action_type == "runtime_setting"


def test_pending_proposal_from_setting_rejects_unknown_key() -> None:
    from ylang.console.proposals import pending_proposal_from_setting

    assert pending_proposal_from_setting(key="auth_token", value="x") is None
    proposal = pending_proposal_from_setting(
        key="improver_critique",
        value="true",
        rationale="Enable critique",
    )
    assert proposal is not None
    assert proposal.proposal_id == "setting:improver_critique=true"
    assert proposal.setting_key == "improver_critique"
    assert proposal.setting_value == "true"


def test_applied_proposal_no_longer_listed(ylang_deps: YlangDeps) -> None:
    """After Apply, the same proposal id must leave the pending list."""
    store = ylang_deps.store
    runtime = RuntimeSettingsStore(store._connection)
    audit = ApplyAuditStore(store._connection)
    clear_aggregate_cache()

    for _ in range(6):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="openai/gpt-4o",
            prompt_tokens=10,
            cost=0.01,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=100,
            success=True,
            improver_validated=True,
            improver_changed=True,
        )

    window = _wide_window()
    before = collect_pending_proposals(store, store._connection, window)
    assert any(item.proposal_id == "suggestion:improver-accept-rate-low" for item in before)

    apply_proposal(
        "suggestion:improver-accept-rate-low",
        store=store,
        library=ylang_deps.library,
        connection=store._connection,
        runtime_store=runtime,
        audit_store=audit,
        window=window,
    )
    after = collect_pending_proposals(store, store._connection, window)
    assert all(item.proposal_id != "suggestion:improver-accept-rate-low" for item in after)


def test_mask_secret_caps_bullet_length() -> None:
    from ylang.core.runtime_settings import mask_secret

    long_key = "sk-" + ("a" * 100)
    masked = mask_secret(long_key, visible=4, max_bullets=12)
    assert masked.endswith(long_key[-4:])
    assert masked.count("•") == 12
    assert len(masked) < len(long_key)


def test_optimization_suggestion_shapes_are_concrete(ylang_deps: YlangDeps) -> None:
    from ylang.usage.optimizer import generate_optimization_suggestions, serialize_suggestion

    store = ylang_deps.store
    clear_aggregate_cache()
    for _ in range(6):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="openai/gpt-4o",
            prompt_tokens=10,
            cost=0.01,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=100,
            success=True,
            improver_validated=True,
            improver_changed=True,
        )
    suggestions = generate_optimization_suggestions(store, _wide_window())
    applyable = [item for item in suggestions if item.apply_action]
    assert applyable
    for item in applyable:
        serialized = serialize_suggestion(item)
        assert serialized["apply_action"] in {"runtime_setting", "learned_template"}
        if item.apply_action == "runtime_setting":
            assert item.setting_key
            assert item.setting_value
            assert "setting_key" in serialized
            assert "setting_value" in serialized
        if item.apply_action == "learned_template":
            assert item.template_id
            assert "template_id" in serialized
