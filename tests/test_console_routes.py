"""Tests for the Ylang admin console HTTP routes."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from ylang.console import register_console_routes
from ylang.gateway.routes import register_gateway_routes
from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.mcp.deps import YlangDeps
from ylang.settings import ProviderKeys, Settings

_AUTH_HEADERS = {"Authorization": "Bearer secret-token"}


@pytest.fixture
def console_client(
    ylang_deps: YlangDeps, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setenv("YLANG_AUTH_TOKEN", "secret-token")
    settings = Settings(
        transport="http",
        auth_token="secret-token",
        provider_keys=ProviderKeys(openai="test-key"),
    )
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="test-key"),
    )
    engine = Engine(ylang_deps.store, surface="gateway", router=router)
    server = FastMCP("ylang-test", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    register_console_routes(server, ylang_deps, settings, gateway_engine=engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), "secret-token")
    return TestClient(app)


def test_console_redirects_unauthenticated_to_login(console_client: TestClient) -> None:
    response = console_client.get("/console", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/console/login")


def test_console_login_page_public(console_client: TestClient) -> None:
    response = console_client.get("/console/login")
    assert response.status_code == 200
    assert "Ylang Console" in response.text


def test_console_login_sets_cookie(console_client: TestClient) -> None:
    response = console_client.post(
        "/console/login",
        data={"token": "secret-token", "next": "/console"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "ylang_token=" in response.headers.get("set-cookie", "")


def test_console_overview_renders(console_client: TestClient) -> None:
    response = console_client.get("/console", headers=_AUTH_HEADERS)
    assert response.status_code == 200
    assert "Ylang" in response.text
    assert "Test improver" in response.text
    assert 'model: "auto"' in response.text
    assert "claude-sonnet-4-5" not in response.text


def test_console_improve_preview_defaults_to_auto(
    console_client: TestClient, ylang_deps: YlangDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Improve-preview omits a forced Claude slug and routes via model=auto."""
    from ylang.improver.types import ImprovementResult

    captured: dict[str, object] = {}

    def _fake_improve(
        text: str,
        tool: str,
        *,
        model: str | None = None,
        context: object = None,
        mode: str | None = None,
        **_kwargs: object,
    ) -> ImprovementResult:
        captured["model"] = model
        return ImprovementResult(
            original=text,
            improved=text + " improved",
            changes=[],
            validated=True,
            auto_apply_default=False,
            cursor_mode=mode or "agent",  # type: ignore[arg-type]
            rejection_reason=None,
        )

    monkeypatch.setattr(ylang_deps.improver, "improve", _fake_improve)
    response = console_client.post(
        "/console/api/improve-preview",
        headers={**_AUTH_HEADERS, "Content-Type": "application/json"},
        json={"text": "fix the bug", "mode": "agent"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert captured["model"] == "auto"


def test_usage_redirects_to_console(console_client: TestClient) -> None:
    response = console_client.get(
        "/usage", headers=_AUTH_HEADERS, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/console/usage"


def test_console_settings_post_and_reset(console_client: TestClient) -> None:
    response = console_client.post(
        "/console/settings",
        headers=_AUTH_HEADERS,
        data={"daily_budget_usd": "10", "improver_critique": "on"},
    )
    assert response.status_code == 200
    assert "Parameters saved" in response.text
    reset = console_client.post(
        "/console/settings",
        headers=_AUTH_HEADERS,
        data={"reset_key": "daily_budget_usd"},
    )
    assert reset.status_code == 200


def test_console_template_save_with_params(console_client: TestClient) -> None:
    save = console_client.post(
        "/console/templates/save",
        headers=_AUTH_HEADERS,
        data={
            "template_id": "param-template",
            "name": "Param Template",
            "body": "Task: {task}",
            "param_name": "task",
            "param_description": "The task",
            "param_default": "review",
        },
        follow_redirects=False,
    )
    assert save.status_code == 303
    page = console_client.get(
        "/console/templates?id=param-template",
        headers=_AUTH_HEADERS,
    )
    assert "Improve with AI" in page.text
    assert "Preview render" in page.text
    assert 'value="task"' in page.text


def test_console_template_save_auto_detects_params(
    console_client: TestClient, ylang_deps: YlangDeps
) -> None:
    """Placeholders in body become params even when Detect was not clicked."""
    save = console_client.post(
        "/console/templates/save",
        headers=_AUTH_HEADERS,
        data={
            "template_id": "auto-param-template",
            "name": "Auto Param Template",
            "body": "Do {task} in {{lang}}",
        },
        follow_redirects=False,
    )
    assert save.status_code == 303
    stored = ylang_deps.library.recall("auto-param-template")
    assert stored is not None
    assert [item.name for item in stored.params] == ["task", "lang"]
    assert stored.params[0].description == ""
    assert stored.params[0].default is None
    page = console_client.get(
        "/console/templates?id=auto-param-template",
        headers=_AUTH_HEADERS,
    )
    assert 'value="task"' in page.text
    assert 'value="lang"' in page.text
    # Browse-first layout still intact
    assert page.text.index("Browse templates") < page.text.index('id="template-create"')


def test_console_template_save_preserves_form_params_when_merging(
    console_client: TestClient, ylang_deps: YlangDeps
) -> None:
    """Declared form params keep description/default; new body placeholders append."""
    save = console_client.post(
        "/console/templates/save",
        headers=_AUTH_HEADERS,
        data={
            "template_id": "merge-param-template",
            "name": "Merge Param Template",
            "body": "Do {task} for {{lang}}",
            "param_name": "task",
            "param_description": "What to do",
            "param_default": "review",
        },
        follow_redirects=False,
    )
    assert save.status_code == 303
    stored = ylang_deps.library.recall("merge-param-template")
    assert stored is not None
    assert [item.name for item in stored.params] == ["task", "lang"]
    assert stored.params[0].description == "What to do"
    assert stored.params[0].default == "review"
    assert stored.params[1].description == ""
    assert stored.params[1].default is None


def test_console_render_template_api(console_client: TestClient) -> None:
    response = console_client.post(
        "/console/api/render-template",
        headers=_AUTH_HEADERS,
        json={"body": "Hello {name}", "param_values": {"name": "world"}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["rendered"] == "Hello world"


def test_console_template_save_and_delete(console_client: TestClient) -> None:
    save = console_client.post(
        "/console/templates/save",
        headers=_AUTH_HEADERS,
        data={
            "template_id": "test-ui-template",
            "name": "UI Template",
            "body": "Hello {name}",
        },
        follow_redirects=False,
    )
    assert save.status_code == 303
    page = console_client.get(
        "/console/templates?id=test-ui-template",
        headers=_AUTH_HEADERS,
    )
    assert "Hello {name}" in page.text
    assert "template-edit" in page.text
    assert "Browse templates" in page.text
    assert "template-create" in page.text
    assert "New template" in page.text
    assert "Detect from body" in page.text
    assert "Unused only" in page.text
    assert "Usage" in page.text
    # Browse-first: table toolbar appears before create disclosure
    assert page.text.index("Browse templates") < page.text.index('id="template-create"')
    unused = console_client.get(
        "/console/templates?unused=1&source=user",
        headers=_AUTH_HEADERS,
    )
    assert unused.status_code == 200
    assert 'name="unused"' in unused.text
    assert "checked" in unused.text
    delete = console_client.post(
        "/console/templates/delete",
        headers=_AUTH_HEADERS,
        data={"template_id": "test-ui-template"},
        follow_redirects=False,
    )
    assert delete.status_code == 303


def test_console_templates_pagination_and_filters(console_client: TestClient) -> None:
    for index in range(15):
        console_client.post(
            "/console/templates/save",
            headers=_AUTH_HEADERS,
            data={
                "template_id": f"page-t-{index:02d}",
                "name": f"Page Template {index}",
                "body": f"Body {index}",
            },
        )
    response = console_client.get(
        "/console/templates?per_page=10&page=2&sort=id&source=user",
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert "Showing 11" in response.text
    assert "page-t-14" in response.text
    assert 'title="Edit"' in response.text
    assert 'title="Delete"' in response.text
    assert "Previous" in response.text


def test_console_facts_crud(console_client: TestClient) -> None:
    create = console_client.post(
        "/console/facts",
        headers=_AUTH_HEADERS,
        data={"fact": "prefers typescript", "scope": "private", "workspace": "ylang"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    assert "msg=" in create.headers["location"]
    listing = console_client.get("/console/facts", headers=_AUTH_HEADERS)
    assert listing.status_code == 200
    assert "prefers typescript" in listing.text
    assert "Browse facts" in listing.text
    assert 'title="Edit"' in listing.text
    assert 'title="Delete"' in listing.text
    update = console_client.post(
        "/console/facts/update",
        headers=_AUTH_HEADERS,
        data={
            "fact_id": "1",
            "fact": "prefers python",
            "scope": "shareable",
            "workspace": "ylang",
        },
        follow_redirects=False,
    )
    assert update.status_code == 303
    edited = console_client.get("/console/facts?id=1", headers=_AUTH_HEADERS)
    assert "prefers python" in edited.text
    assert "fact-edit" in edited.text
    delete = console_client.post(
        "/console/facts/delete",
        headers=_AUTH_HEADERS,
        data={"fact_id": "1"},
        follow_redirects=False,
    )
    assert delete.status_code == 303


def test_console_facts_seed_samples_and_filters(console_client: TestClient) -> None:
    empty = console_client.get("/console/facts", headers=_AUTH_HEADERS)
    assert "No facts yet" in empty.text
    assert "Add sample facts" in empty.text
    assert "Suggest facts with AI" in empty.text
    seed = console_client.post(
        "/console/facts/seed-samples",
        headers=_AUTH_HEADERS,
        follow_redirects=False,
    )
    assert seed.status_code == 303
    listing = console_client.get("/console/facts", headers=_AUTH_HEADERS)
    assert "Prefer TypeScript" in listing.text
    filtered = console_client.get(
        "/console/facts?scope=private&q=scoped",
        headers=_AUTH_HEADERS,
    )
    assert filtered.status_code == 200
    assert "Keep changes small" in filtered.text
    again = console_client.post(
        "/console/facts/seed-samples",
        headers=_AUTH_HEADERS,
        follow_redirects=False,
    )
    assert again.status_code == 303
    assert "already+exist" in again.headers["location"]


def test_console_overview_facts_cta_when_empty(console_client: TestClient) -> None:
    response = console_client.get("/console", headers=_AUTH_HEADERS)
    assert response.status_code == 200
    assert "Suggest facts with AI" in response.text
    assert "/console/facts?suggest=1" in response.text


def test_console_suggest_facts_api_and_accept(
    console_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ylang.console.route_modules.api.suggest_facts_from_usage",
        lambda *_args, **_kwargs: {
            "ok": True,
            "suggestions": [
                {
                    "fact": "Prefer Vitest for unit tests",
                    "scope": "shareable",
                    "workspace": "ylang",
                    "rationale": "from samples",
                }
            ],
        },
    )
    suggest = console_client.post(
        "/console/api/suggest-facts",
        headers=_AUTH_HEADERS,
    )
    assert suggest.status_code == 200
    payload = suggest.json()
    assert payload["ok"] is True
    assert payload["suggestions"][0]["fact"] == "Prefer Vitest for unit tests"

    import json

    accept = console_client.post(
        "/console/facts/accept-suggestions",
        headers=_AUTH_HEADERS,
        data={
            "selected": json.dumps(
                {
                    "fact": "Prefer Vitest for unit tests",
                    "scope": "shareable",
                    "workspace": "ylang",
                }
            )
        },
        follow_redirects=False,
    )
    assert accept.status_code == 303
    assert "Saved" in accept.headers["location"]
    listing = console_client.get("/console/facts", headers=_AUTH_HEADERS)
    assert "Prefer Vitest for unit tests" in listing.text
    overview = console_client.get("/console", headers=_AUTH_HEADERS)
    assert "Add facts" not in overview.text
    assert 'href="/console/facts?suggest=1"' not in overview.text


def test_console_data_browser(console_client: TestClient) -> None:
    response = console_client.get("/console/data?table=usage", headers=_AUTH_HEADERS)
    assert response.status_code == 200
    assert "usage" in response.text
    assert "Domain views" in response.text
    assert 'href="/console/data?table=feedback_events"' in response.text
    assert "All tables" in response.text


def test_console_control_renders(console_client: TestClient) -> None:
    response = console_client.get("/console/control", headers=_AUTH_HEADERS)
    assert response.status_code == 200
    assert "Operator Hub" in response.text
    assert "Top applyable proposals" in response.text
    assert "Optimize Ylang" in response.text
    assert "Diagnose" in response.text
    assert "Propose" in response.text
    assert "Apply" in response.text
    assert "Measure" in response.text
    assert "Improver accept (7d)" in response.text
    assert "Polish ratio (7d)" in response.text
    assert "Performance ratio (7d)" in response.text
    assert 'href="/console/settings">Parameters</a>' in response.text
    assert 'href="/console#improver-sandbox"' in response.text
    assert "Control" in response.text
    assert "Add memory facts" in response.text
    assert "/console/facts?suggest=1" in response.text
    assert "POST /console/api/suggest-facts" in response.text


def test_console_improver_shows_quality_ratios(console_client: TestClient) -> None:
    response = console_client.get("/console/improver", headers=_AUTH_HEADERS)
    assert response.status_code == 200
    assert "Polish ratio" in response.text
    assert "Performance ratio" in response.text
    assert "Performance" in response.text  # per-mode column


def test_console_overview_shows_quality_ratios(console_client: TestClient) -> None:
    response = console_client.get("/console", headers=_AUTH_HEADERS)
    assert response.status_code == 200
    assert "Polish ratio" in response.text
    assert "Performance ratio" in response.text


def test_console_settings_presets(console_client: TestClient) -> None:
    response = console_client.get("/console/settings", headers=_AUTH_HEADERS)
    assert response.status_code == 200
    assert "Parameters" in response.text
    assert "Fast / cheap" in response.text
    assert "Quality" in response.text
    assert "presetFast" in response.text
    assert "Effective:" in response.text
    assert 'id="params-routing"' in response.text
    assert 'id="params-improver"' in response.text
    assert 'id="params-limits"' in response.text
    assert 'id="params-flags"' in response.text
    assert "Routing" in response.text
    assert "Limits" in response.text
    assert "env default" in response.text
    assert 'name="pattern_detector"' in response.text
    assert "<select" in response.text
    assert 'value="lexical"' in response.text
    assert 'value="semantic"' in response.text
    assert "Impact estimate" in response.text
    assert "favors latency" in response.text
    assert "preferred-picker" in response.text or "Preferred template" in response.text


def test_console_templates_toxic_quarantine_endpoint(
    console_client: TestClient, ylang_deps: YlangDeps
) -> None:
    from datetime import datetime, timezone

    ylang_deps.library.save(
        "toxic-route",
        name="Toxic Route",
        body="toxic",
        params=[],
        source="user",
        visibility="private",
    )
    for _ in range(3):
        ylang_deps.store.write_usage(
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
            improver_context_templates="toxic-route",
            improver_validated=True,
            improver_changed=True,
        )
    page = console_client.get("/console/templates?toxic=1", headers=_AUTH_HEADERS)
    assert page.status_code == 200
    assert "toxic-route" in page.text
    assert "Quarantine toxic (0% accept)" in page.text
    assert 'name="toxic"' in page.text

    archived = console_client.post(
        "/console/templates/archive-toxic",
        headers=_AUTH_HEADERS,
        data={},
        follow_redirects=False,
    )
    assert archived.status_code == 303
    assert "Quarantined" in archived.headers["location"]
    recalled = ylang_deps.library.recall("toxic-route")
    assert recalled is not None
    assert recalled.visibility == "archived"


def test_console_data_search_and_mutators(console_client: TestClient, ylang_deps) -> None:
    ylang_deps.store.write_usage(
        surface="mcp",
        activity="improve:agent",
        model_used="openai/gpt-4o",
        prompt_tokens=10,
        cost=0.01,
        improver_fired=True,
        improver_accepted=True,
        latency_ms=50,
        success=True,
    )
    filtered = console_client.get(
        "/console/data?table=usage&q=improve",
        headers=_AUTH_HEADERS,
    )
    assert filtered.status_code == 200
    assert "Search rows" in filtered.text
    assert "Purge old usage" in filtered.text

    clear = console_client.post(
        "/console/data/clear-cache",
        headers=_AUTH_HEADERS,
        data={"confirm": "CLEAR", "table": "improver_cache"},
        follow_redirects=False,
    )
    assert clear.status_code == 303
    assert "improver_cache" in clear.headers["location"]


def test_console_nav_gates_experiments_and_feedback(console_client: TestClient) -> None:
    overview = console_client.get("/console", headers=_AUTH_HEADERS)
    assert overview.status_code == 200
    assert "Advanced" in overview.text
    primary = overview.text.split('class="nav-advanced"', 1)[0]
    assert "Experiments" not in primary
    assert "Feedback" not in primary
    # Deep links still work
    experiments = console_client.get("/console/experiments", headers=_AUTH_HEADERS)
    assert experiments.status_code == 200
    assert "Experiments are off" in experiments.text
    feedback = console_client.get("/console/feedback", headers=_AUTH_HEADERS)
    assert feedback.status_code == 200
    assert "Edit feedback is off" in feedback.text

    console_client.post(
        "/console/settings",
        headers=_AUTH_HEADERS,
        data={"experiments": "on", "edit_feedback": "on"},
    )
    enabled = console_client.get("/console", headers=_AUTH_HEADERS)
    primary_on = enabled.text.split('class="nav-advanced"', 1)[0]
    assert "Experiments" in primary_on
    assert "Feedback" in primary_on


def test_console_static_chart(console_client: TestClient) -> None:
    response = console_client.get("/console/static/chart.umd.min.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript") or response.content
