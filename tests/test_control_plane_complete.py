"""Close remaining control-plane gates with automated evidence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import litellm
import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from ylang.cli.ops import run_doctor_cli, run_purge_traces_cli
from ylang.console import register_console_routes
from ylang.console.proposals import collect_pending_proposals
from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.routing_reason import build_routing_reason, routing_one_liner
from ylang.gateway.routes import register_gateway_routes
from ylang.mcp.auth import BearerTokenMiddleware, session_cookie_kwargs
from ylang.mcp.deps import YlangDeps
from ylang.mcp.serializers import _serialize_usage
from ylang.settings import ProviderKeys, Settings
from ylang.usage.evaluation import (
    SIGNAL_CATALOG,
    assemble_evaluation,
    classify_signal,
    compare_usage_dimensions,
)
from ylang.usage.operator_metrics import routing_metrics, today_metrics
from ylang.usage.store import UsageWindow, open_store

_AUTH = {"Authorization": "Bearer secret-token"}


def _mock_response(
    content: str = "ok",
    *,
    model: str = "openai/gpt-4o",
    tool_calls: list | None = None,
) -> MagicMock:
    message = MagicMock(content=content, tool_calls=tool_calls)
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    response.model = model
    response.usage = MagicMock(prompt_tokens=3, completion_tokens=5)
    response._hidden_params = {"response_cost": 0.001}
    return response


def _engine(tmp_path: Path, *, capture_level: str = "minimal") -> Engine:
    store = open_store(tmp_path / "cp.db")
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="test-key"),
        fallback_model="ollama/qwen2.5",
        usage_store=store,
    )
    return Engine(
        store,
        surface="gateway",
        router=router,
        capture_level=capture_level,  # type: ignore[arg-type]
    )


def test_stream_persists_single_trace(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    def stream_side_effect(**kwargs: object):
        chunk = MagicMock()
        chunk.choices = [
            MagicMock(delta=MagicMock(content="hi", tool_calls=None), finish_reason=None)
        ]
        chunk.model = "openai/gpt-4o"
        chunk.usage = MagicMock(prompt_tokens=2, completion_tokens=4)
        chunk._hidden_params = {"response_cost": 0.0}
        return [chunk]

    with patch("ylang.core.engine.litellm.completion", side_effect=stream_side_effect):
        chunks = list(
            engine.complete_stream(
                [{"role": "user", "content": "stream me"}],
                "code",
                selected_route="route-code",
            )
        )
    assert chunks
    rows = engine.store.recall_usage(UsageWindow.last_hours(1))
    assert len(rows) == 1
    assert rows[0].trace_id
    assert rows[0].selected_route == "route-code"
    assert rows[0].routing_reason_json


def test_tool_calls_json_traced(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q":"x"}'},
        }
    ]
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_response("ok", tool_calls=tool_calls),
    ):
        engine.complete([{"role": "user", "content": "call tool"}], "code")
    row = engine.store.recall_usage(UsageWindow.last_hours(1))[0]
    assert row.tool_calls_json is not None
    payload = json.loads(row.tool_calls_json)
    assert payload[0]["name"] == "lookup"
    assert "arguments" not in payload[0]  # minimal capture


def test_budget_reason_code_when_over_cap(tmp_path: Path) -> None:
    store = open_store(tmp_path / "budget.db")
    now = datetime.now(timezone.utc)
    store.write_usage(
        surface="t",
        activity="code",
        model_used="openai/gpt-4o",
        prompt_tokens=1,
        cost=1.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now,
    )
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o", "ollama/qwen2.5"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="k"),
        fallback_model="ollama/qwen2.5",
        daily_budget_usd=0.5,
        usage_store=store,
    )
    chain = router.build_attempt_chain("code")
    reason = build_routing_reason(
        router, "code", attempt_chain=chain, selected=chain[0]
    )
    codes = [step["code"] for step in reason["steps"]]
    assert "budget_constraint" in codes


def test_signal_catalog_and_evaluation_assembly(tmp_path: Path) -> None:
    assert classify_signal("improver_accepted") == "user"
    assert classify_signal("silence_as_success") == "unknown"
    assert SIGNAL_CATALOG["latency_ms"] == "objective"
    engine = _engine(tmp_path)
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_response("ok"),
    ):
        engine.complete([{"role": "user", "content": "hi"}], "code")
    row = engine.store.recall_usage(UsageWindow.last_hours(1))[0]
    evaluation = assemble_evaluation(row)
    classes = {item["class"] for item in evaluation["signals"]}
    assert "objective" in classes
    assert row.evaluation_json is not None
    assert json.loads(row.evaluation_json)["schema"] == 1
    policy = json.loads(row.policy_decision_json or "{}")
    assert "evaluation" not in policy


def test_gateway_parent_trace_header(
    ylang_deps: YlangDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YLANG_AUTH_TOKEN", "secret-token")
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="k"),
        fallback_model="ollama/qwen2.5",
    )
    engine = Engine(ylang_deps.store, surface="gateway", router=router)
    server = FastMCP("ylang-parent", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), token="secret-token")
    client = TestClient(app)
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_response("pong"),
    ):
        response = client.post(
            "/v1/chat/completions",
            headers={
                **_AUTH,
                "X-Ylang-Parent-Trace": "parent-abc",
                "X-Ylang-Trace-Id": "child-xyz",
                "X-Ylang-Session": "sess-1",
                "X-Ylang-Workspace": "ws-main",
            },
            json={
                "model": "route-code",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert response.status_code == 200
    row = ylang_deps.store.recall_usage(UsageWindow.last_hours(1))[0]
    assert row.parent_trace_id == "parent-abc"
    assert row.trace_id == "child-xyz"
    assert row.session_id == "sess-1"
    assert row.workspace == "ws-main"


def test_migration_12_evaluation_json(tmp_path: Path) -> None:
    store = open_store(tmp_path / "eval2.db")
    columns = {
        row[1]
        for row in store._connection.execute("PRAGMA table_info(usage)").fetchall()
    }
    assert "evaluation_json" in columns
    store.close()


def test_migration_13_phase_b_columns(tmp_path: Path) -> None:
    from ylang.core.migrations import USAGE_TRACE_PHASE_B_COLUMNS

    store = open_store(tmp_path / "phaseb.db")
    columns = {
        row[1]
        for row in store._connection.execute("PRAGMA table_info(usage)").fetchall()
    }
    for name, _ddl in USAGE_TRACE_PHASE_B_COLUMNS:
        assert name in columns
    store.close()


def test_engine_phase_b_session_sets_retention(tmp_path: Path) -> None:
    engine = _engine(tmp_path, capture_level="redacted")
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_response("ok"),
    ):
        result = engine.complete(
            [{"role": "user", "content": "hi"}],
            "code",
            session_id="s-9",
            workspace="ws-a",
            context_sources_json='["conversation"]',
            mcp_tool="improve_prompt",
        )
    assert result.trace_id
    row = engine.store.recall_usage(UsageWindow.last_hours(1))[0]
    assert row.session_id == "s-9"
    assert row.workspace == "ws-a"
    assert row.context_sources_json == '["conversation"]'
    assert row.mcp_server == "ylang"
    assert row.retention_until is not None
    assert row.capture_level == "redacted"


def test_compare_usage_dimensions(tmp_path: Path) -> None:
    store = open_store(tmp_path / "dims.db")
    for model in ("openai/gpt-4o", "ollama/qwen2.5"):
        store.write_usage(
            surface="gateway",
            activity="code",
            model_used=model,
            prompt_tokens=1,
            cost=0.1,
            improver_fired=False,
            improver_accepted=False,
            latency_ms=10,
            success=True,
        )
    rows = compare_usage_dimensions(store, UsageWindow.last_hours(1))
    assert any(item.dimension == "model" for item in rows)


def test_experiments_never_auto_apply(
    ylang_deps: YlangDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YLANG_AUTH_TOKEN", "secret-token")
    settings = Settings(transport="http", auth_token="secret-token")
    engine = Engine(
        ylang_deps.store,
        surface="gateway",
        router=ModelRouter(
            activity_model_lists={
                "code": ["openai/gpt-4o"],
                "search": ["openai/gpt-4o"],
                "reason": ["openai/gpt-4o"],
                "improve": ["openai/gpt-4o"],
                "other": ["openai/gpt-4o"],
            },
            provider_keys=ProviderKeys(),
        ),
    )
    server = FastMCP("ylang-cp", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    register_console_routes(server, ylang_deps, settings, gateway_engine=engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), token="secret-token")
    client = TestClient(app)
    page = client.get("/console/proposals", headers=_AUTH)
    assert page.status_code == 200
    assert "Nothing is auto-applied" in page.text
    # Collecting proposals must not mutate runtime settings by itself.
    before = dict(ylang_deps.store._connection.execute(
        "SELECT key, value FROM runtime_settings"
    ).fetchall())
    collect_pending_proposals(
        ylang_deps.store,
        ylang_deps.store._connection,
        UsageWindow.last_days(7),
    )
    after = dict(ylang_deps.store._connection.execute(
        "SELECT key, value FROM runtime_settings"
    ).fetchall())
    assert before == after


def test_operator_hubs_use_real_data(
    ylang_deps: YlangDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YLANG_AUTH_TOKEN", "secret-token")
    settings = Settings(transport="http", auth_token="secret-token")
    ylang_deps.store.write_usage(
        surface="gateway",
        activity="code",
        model_used="ollama/qwen2.5",
        prompt_tokens=2,
        cost=0.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=42,
        success=True,
        routing_reason_json=json.dumps(
            {
                "schema": 1,
                "selected": "ollama/qwen2.5",
                "steps": [{"code": "configured_preference"}],
            }
        ),
        capture_level="minimal",
    )
    engine = Engine(ylang_deps.store, surface="gateway", router=ModelRouter())
    server = FastMCP("ylang-hubs", streamable_http_path="/mcp")
    register_console_routes(server, ylang_deps, settings, gateway_engine=engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), token="secret-token")
    client = TestClient(app)
    today = client.get("/console/today", headers=_AUTH)
    assert today.status_code == 200
    assert "42" in today.text or "Requests" in today.text
    assert client.get("/console/quality", headers=_AUTH).status_code == 200
    routing = client.get("/console/routing", headers=_AUTH)
    assert routing.status_code == 200
    assert "ollama/qwen2.5" in routing.text
    privacy = client.get("/console/privacy", headers=_AUTH)
    assert privacy.status_code == 200
    assert "cannot observe" in privacy.text
    metrics = today_metrics(ylang_deps.store, UsageWindow.last_hours(24))
    assert metrics.requests >= 1
    assert metrics.local_requests >= 1


def test_serialize_usage_includes_routing_explanation(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_response("ok"),
    ):
        engine.complete([{"role": "user", "content": "hi"}], "code")
    row = engine.store.recall_usage(UsageWindow.last_hours(1))[0]
    payload = _serialize_usage(row)
    assert "routing_explanation" in payload
    assert payload["routing_explanation"].startswith("Selected ")


def test_purge_traces_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "purge.db"
    store = open_store(db_path)
    old = datetime.now(timezone.utc) - timedelta(days=120)
    store.write_usage(
        surface="t",
        activity="code",
        model_used="ollama/qwen2.5",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=True,
        improver_accepted=False,
        improver_input_sample="old secret body",
        prompt_body_redacted="old redacted",
        latency_ms=1,
        success=True,
        timestamp=old,
        capture_level="redacted",
    )
    store.close()
    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    assert run_purge_traces_cli(["--older-than-days", "90"]) == 0
    store = open_store(db_path)
    rows = store.recall_usage(
        UsageWindow(
            since=old - timedelta(days=1),
            until=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    assert rows[0].prompt_body_redacted is None
    assert rows[0].improver_input_sample is None
    store.close()


def test_doctor_warns_on_all_interfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("YLANG_STORAGE_PATH", str(tmp_path / "doc.db"))
    open_store(tmp_path / "doc.db").close()
    monkeypatch.setenv("YLANG_TRANSPORT", "http")
    monkeypatch.setenv("YLANG_HOST", "0.0.0.0")
    monkeypatch.setenv("YLANG_AUTH_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    run_doctor_cli([])
    out = capsys.readouterr().out
    assert "all interfaces" in out


def test_session_cookie_httponly_samesite() -> None:
    kwargs = session_cookie_kwargs()
    assert kwargs["httponly"] is True
    assert kwargs["samesite"] == "lax"


def test_no_public_apache_proxy_scripts() -> None:
    deploy = Path(__file__).resolve().parents[1] / "deploy"
    apache = deploy / "apache"
    assert not apache.exists() or not any(apache.glob("*"))
    forbidden = (
        "install-ylang-path-proxy.sh",
        "install-ylang-vhost.sh",
        "ylang-path-proxy.conf",
        "ylang.stelliane.dev.conf",
    )
    for name in forbidden:
        assert not (deploy / "apache" / name).exists()


def test_routes_py_new_removed() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ylang"
        / "console"
        / "routes.py.new"
    )
    assert not path.exists()


def test_private_defaults_minimal_hash_not_body(tmp_path: Path) -> None:
    engine = _engine(tmp_path, capture_level="minimal")
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_response("ok"),
    ):
        engine.complete(
            [{"role": "user", "content": "sensitive prompt body here"}],
            "code",
        )
    row = engine.store.recall_usage(UsageWindow.last_hours(1))[0]
    assert row.capture_level == "minimal"
    assert row.prompt_hash
    assert row.prompt_body_redacted is None


def test_gateway_selected_route_traced(
    ylang_deps: YlangDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YLANG_AUTH_TOKEN", "secret-token")
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="k"),
        fallback_model="ollama/qwen2.5",
    )
    engine = Engine(ylang_deps.store, surface="gateway", router=router)
    server = FastMCP("ylang-gw", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), token="secret-token")
    client = TestClient(app)
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_response("pong"),
    ):
        response = client.post(
            "/v1/chat/completions",
            headers=_AUTH,
            json={
                "model": "route-code",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert response.status_code == 200
    row = ylang_deps.store.recall_usage(UsageWindow.last_hours(1))[0]
    assert row.selected_route == "route-code"
    assert row.trace_id
    assert routing_one_liner(row.routing_reason_json).startswith("Selected ")


def test_fallback_rate_limit_traced(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    def side_effect(**kwargs: object) -> MagicMock:
        if kwargs["model"] == "openai/gpt-4o":
            raise litellm.RateLimitError("rate", "openai", "gpt-4o")
        return _mock_response("ok", model=str(kwargs["model"]))

    with patch("ylang.core.engine.litellm.completion", side_effect=side_effect):
        result = engine.complete([{"role": "user", "content": "hi"}], "code")
    assert result.success
    row = engine.store.recall_usage(UsageWindow.last_hours(1))[0]
    assert row.fallback_events_json
    metrics = routing_metrics(engine.store, UsageWindow.last_hours(1))
    assert metrics.fallback_count >= 1
