"""Tests that improve:* completions honor models_improve routing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ylang.core import Engine
from ylang.core.migrations import run_migrations
from ylang.core.model_router import ModelRouter
from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.core.stores import open_stores
from ylang.improver import Improver
from ylang.settings import ProviderKeys, Settings
from ylang.usage.store import UsageStore, open_store


def test_engine_hot_reloads_models_improve_from_runtime(tmp_path: object) -> None:
    db = tmp_path / "hot.db"  # type: ignore[operator]
    store = open_store(db)
    base = Settings()
    engine = Engine.from_settings(store, surface="mcp", settings=base)

    assert engine.router.ordered_candidates("improve")[0] == (
        base.activity_model_lists["improve"][0]
    )

    runtime = RuntimeSettingsStore(store._connection)
    runtime.set(
        "models_improve",
        "mistral/mistral-small-latest,openai/gpt-4o-mini",
    )

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="ok"))
    ]
    mock_response.model = "mistral/mistral-small-latest"
    mock_response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
    mock_response._hidden_params = {"response_cost": 0.0}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response):
        engine.complete(
            [{"role": "user", "content": "ping"}],
            activity="improve:agent",
        )

    assert engine.router.ordered_candidates("improve") == [
        "mistral/mistral-small-latest",
        "openai/gpt-4o-mini",
    ]


def test_improver_uses_models_improve_not_cursor_slug(tmp_path: object) -> None:
    db = tmp_path / "improve.db"  # type: ignore[operator]
    with db.open("w"):
        pass
    stores = open_stores(db)
    settings = Settings()
    settings_data = settings.model_dump()
    settings_data["activity_model_lists"] = {
        **settings.activity_model_lists,
        "improve": [
            "mistral/mistral-small-latest",
            "openai/gpt-4o-mini",
        ],
    }
    settings_data["provider_keys"] = ProviderKeys(mistral="test-key")
    effective = Settings(**settings_data)
    router = ModelRouter.from_settings(effective, usage_store=stores.store)
    engine = Engine(stores.store, surface="mcp", router=router, base_settings=effective)
    improver = Improver(engine)

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps({"improved": "Fix the bug in main.py", "changes": []})
            )
        )
    ]
    mock_response.model = "mistral/mistral-small-latest"
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_response._hidden_params = {"response_cost": 0.001}

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response) as mock:
        result = improver.improve(
            "fix bug",
            "cursor-agent",
            model="claude-sonnet-4-5",
        )

    assert result.improved == "Fix the bug in main.py"
    assert mock.call_args.kwargs["model"] == "mistral/mistral-small-latest"


@pytest.fixture
def migrated_connection(tmp_path: object):
    db = tmp_path / "runtime-improve.db"  # type: ignore[operator]
    import sqlite3

    connection = sqlite3.connect(db)
    run_migrations(connection)
    yield connection
    connection.close()


def test_merge_settings_models_improve_applied_to_router(
    migrated_connection: object,
) -> None:
    store = UsageStore(migrated_connection)  # type: ignore[arg-type]
    store._ensure_schema()
    runtime = RuntimeSettingsStore(migrated_connection)  # type: ignore[arg-type]
    runtime.set("models_improve", "openai/gpt-4o-mini,mistral/mistral-small-latest")

    base = Settings()
    engine = Engine.from_settings(store, surface="mcp", settings=base)
    engine._refresh_routing()

    assert engine.router.ordered_candidates("improve") == [
        "openai/gpt-4o-mini",
        "mistral/mistral-small-latest",
    ]
