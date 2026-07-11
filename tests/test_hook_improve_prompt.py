"""Tests for Cursor beforeSubmitPrompt hook fail-open behavior."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "deploy/cursor/hooks/ylang-improve-prompt.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("ylang_improve_prompt_hook", _HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook_module():
    return _load_hook_module()


def test_fail_open_emits_continue(hook_module, capsys: pytest.CaptureFixture[str]) -> None:
    hook_module._fail_open()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"continue": True}


def test_run_timed_raises_on_slow_coro(hook_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YLANG_HOOK_TIMEOUT_SEC", "0.05")

    async def slow() -> str:
        await asyncio.sleep(1.0)
        return "late"

    with pytest.raises(TimeoutError, match="slow_label timed out"):
        asyncio.run(hook_module._run_timed(slow(), label="slow_label"))


def test_improve_prompt_timeout_fail_open(
    hook_module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YLANG_HOOK_TIMEOUT_SEC", "0.05")
    payload = {"prompt": "add dark mode toggle", "composer_mode": "agent"}

    async def slow_improve(**_kwargs: object) -> dict[str, str]:
        await asyncio.sleep(1.0)
        return {"improved": "x", "original": "x", "validated": True}

    with (
        patch.object(hook_module, "_load_mcp_config", return_value=("http://127.0.0.1/mcp", "token")),
        patch.object(hook_module, "_call_improve_prompt", side_effect=slow_improve),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"continue": True}
    assert "improve_prompt timed out" in captured.err


def test_unhandled_error_fail_open(
    hook_module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {"prompt": "add dark mode toggle", "composer_mode": "agent"}

    with (
        patch.object(hook_module, "_load_mcp_config", side_effect=RuntimeError("boom")),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"continue": True}
    assert "improve_prompt failed: boom" in captured.err
