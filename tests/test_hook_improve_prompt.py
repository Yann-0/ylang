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

_HOOK_PATH = (
    Path(__file__).resolve().parents[1] / "deploy/cursor/hooks/ylang-improve-prompt.py"
)


def _load_hook_module():
    spec = importlib.util.spec_from_file_location(
        "ylang_improve_prompt_hook", _HOOK_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook_module():
    return _load_hook_module()


def test_fail_open_emits_continue(
    hook_module, capsys: pytest.CaptureFixture[str]
) -> None:
    hook_module._fail_open()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"continue": True}


def test_run_timed_raises_on_slow_coro(
    hook_module, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        patch.object(
            hook_module,
            "_load_mcp_config",
            return_value=("http://127.0.0.1/mcp", "token"),
        ),
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


def test_hook_auto_apply_false_emits_user_message(
    hook_module,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {"prompt": "add dark mode toggle", "composer_mode": "agent"}

    async def fake_improve(**_kwargs: object) -> dict[str, object]:
        return {
            "improved": "Add a dark mode toggle to settings.",
            "original": "add dark mode toggle",
            "validated": True,
            "auto_apply_default": False,
            "cursor_mode": "agent",
            "mode_source": "explicit",
        }

    with (
        patch.object(
            hook_module,
            "_load_mcp_config",
            return_value=("http://127.0.0.1/mcp", "token"),
        ),
        patch.object(hook_module, "_call_improve_prompt", side_effect=fake_improve),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["continue"] is True
    assert "user_message" in output
    assert "updated_input" not in output
    assert "dark mode" in output["user_message"]


def test_hook_auto_apply_true_emits_updated_input(
    hook_module,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {"prompt": "add dark mode toggle", "composer_mode": "agent"}

    async def fake_improve(**_kwargs: object) -> dict[str, object]:
        return {
            "improved": "Add a dark mode toggle to settings.",
            "original": "add dark mode toggle",
            "validated": True,
            "auto_apply_default": True,
            "cursor_mode": "agent",
            "mode_source": "explicit",
        }

    with (
        patch.object(
            hook_module,
            "_load_mcp_config",
            return_value=("http://127.0.0.1/mcp", "token"),
        ),
        patch.object(hook_module, "_call_improve_prompt", side_effect=fake_improve),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["updated_input"]["prompt"] == "Add a dark mode toggle to settings."


def test_has_and_strip_ylang_off(hook_module) -> None:
    assert hook_module._has_ylang_off("ylang-off fix the bug")
    assert hook_module._has_ylang_off("Please /YLANG-OFF and continue")
    assert hook_module._has_ylang_off("do this\nylang-off\nthanks")
    assert not hook_module._has_ylang_off("fix my-ylang-off-tool path")
    assert not hook_module._has_ylang_off("improve this prompt")

    assert (
        hook_module._strip_ylang_off("ylang-off fix the bug") == "fix the bug"
    )
    assert (
        hook_module._strip_ylang_off("/ylang-off\n\nadd dark mode") == "add dark mode"
    )
    assert hook_module._strip_ylang_off("ylang-off") == ""


def test_ylang_off_bypasses_improve_and_strips_marker(
    hook_module,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "prompt": "ylang-off add a dark mode toggle",
        "composer_mode": "agent",
    }

    def _must_not_call(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("improve_prompt must not be called for ylang-off")

    with (
        patch.object(
            hook_module,
            "_load_mcp_config",
            side_effect=AssertionError("MCP config must not be loaded"),
        ),
        patch.object(hook_module, "_call_improve_prompt", side_effect=_must_not_call),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["continue"] is True
    assert output["updated_input"]["prompt"] == "add a dark mode toggle"
    assert "ylang-off" not in output["updated_input"]["prompt"]
    assert "skipped (ylang-off)" in captured.err


def test_ylang_off_only_fail_open(
    hook_module,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {"prompt": "/ylang-off", "composer_mode": "agent"}

    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        hook_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"continue": True}
    assert "skipped (ylang-off)" in captured.err


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, False),
        ({"YLANG_CAPTURE_EDIT_FEEDBACK": ""}, False),
        ({"YLANG_CAPTURE_EDIT_FEEDBACK": "0"}, False),
        ({"YLANG_CAPTURE_EDIT_FEEDBACK": "1"}, True),
        ({"YLANG_CAPTURE_EDIT_FEEDBACK": "true"}, True),
        ({"YLANG_EDIT_FEEDBACK": "yes"}, True),
        ({"YLANG_EDIT_FEEDBACK": "on"}, True),
        (
            {"YLANG_CAPTURE_EDIT_FEEDBACK": "0", "YLANG_EDIT_FEEDBACK": "1"},
            True,
        ),
    ],
)
def test_should_capture_edit_feedback(
    hook_module,
    environ: dict[str, str],
    expected: bool,
) -> None:
    assert hook_module._should_capture_edit_feedback(environ) is expected


def test_capture_edit_feedback_env_records_prompt_edit(
    hook_module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YLANG_CAPTURE_EDIT_FEEDBACK", "1")
    payload = {"prompt": "user edited submit text", "composer_mode": "agent"}
    recorded: list[tuple[str, str]] = []

    async def fake_improve(**_kwargs: object) -> dict[str, object]:
        return {
            "improved": "Improved prompt text from improver.",
            "original": "user edited submit text",
            "validated": True,
            "auto_apply_default": True,
            "cursor_mode": "agent",
            "mode_source": "explicit",
        }

    async def fake_record(
        _url: str, _token: str, improved: str, submitted: str
    ) -> None:
        recorded.append((improved, submitted))

    with (
        patch.object(
            hook_module,
            "_load_mcp_config",
            return_value=("http://127.0.0.1/mcp", "token"),
        ),
        patch.object(hook_module, "_call_improve_prompt", side_effect=fake_improve),
        patch.object(hook_module, "_record_edit_feedback", side_effect=fake_record),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out)["continue"] is True
    # auto_apply keeps the improvement → distance-0 polish sample
    assert recorded == [
        (
            "Improved prompt text from improver.",
            "Improved prompt text from improver.",
        )
    ]
    assert "recorded prompt edit feedback" in captured.err
    assert "kept_as_is=True" in captured.err


def test_capture_edit_feedback_off_skips_record(
    hook_module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("YLANG_CAPTURE_EDIT_FEEDBACK", raising=False)
    monkeypatch.delenv("YLANG_EDIT_FEEDBACK", raising=False)
    payload = {"prompt": "user edited submit text", "composer_mode": "agent"}

    async def fake_improve(**_kwargs: object) -> dict[str, object]:
        return {
            "improved": "Improved prompt text from improver.",
            "original": "user edited submit text",
            "validated": True,
            "auto_apply_default": True,
            "cursor_mode": "agent",
            "mode_source": "explicit",
        }

    def _must_not_record(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("record_prompt_edit must not run when capture is off")

    with (
        patch.object(
            hook_module,
            "_load_mcp_config",
            return_value=("http://127.0.0.1/mcp", "token"),
        ),
        patch.object(hook_module, "_call_improve_prompt", side_effect=fake_improve),
        patch.object(
            hook_module, "_record_edit_feedback", side_effect=_must_not_record
        ),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out)["continue"] is True
    assert "recorded prompt edit feedback" not in captured.err


def test_capture_records_distance_zero_when_unchanged(
    hook_module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YLANG_CAPTURE_EDIT_FEEDBACK", "1")
    same = "already a clear prompt"
    payload = {"prompt": same, "composer_mode": "agent"}
    recorded: list[tuple[str, str]] = []

    async def fake_improve(**_kwargs: object) -> dict[str, object]:
        return {
            "improved": same,
            "original": same,
            "validated": True,
            "auto_apply_default": True,
            "cursor_mode": "agent",
            "mode_source": "explicit",
        }

    async def fake_record(
        _url: str, _token: str, improved: str, submitted: str
    ) -> None:
        recorded.append((improved, submitted))

    with (
        patch.object(
            hook_module,
            "_load_mcp_config",
            return_value=("http://127.0.0.1/mcp", "token"),
        ),
        patch.object(hook_module, "_call_improve_prompt", side_effect=fake_improve),
        patch.object(hook_module, "_record_edit_feedback", side_effect=fake_record),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out)["continue"] is True
    assert recorded == [(same, same)]
    assert "kept_as_is=True" in captured.err


def test_capture_review_path_records_user_prompt(
    hook_module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YLANG_CAPTURE_EDIT_FEEDBACK", "1")
    payload = {"prompt": "rough draft prompt", "composer_mode": "agent"}
    recorded: list[tuple[str, str]] = []

    async def fake_improve(**_kwargs: object) -> dict[str, object]:
        return {
            "improved": "Polished full specification.",
            "original": "rough draft prompt",
            "validated": True,
            "auto_apply_default": False,
            "cursor_mode": "agent",
            "mode_source": "explicit",
        }

    async def fake_record(
        _url: str, _token: str, improved: str, submitted: str
    ) -> None:
        recorded.append((improved, submitted))

    with (
        patch.object(
            hook_module,
            "_load_mcp_config",
            return_value=("http://127.0.0.1/mcp", "token"),
        ),
        patch.object(hook_module, "_call_improve_prompt", side_effect=fake_improve),
        patch.object(hook_module, "_record_edit_feedback", side_effect=fake_record),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out)["continue"] is True
    assert recorded == [("Polished full specification.", "rough draft prompt")]
    assert "kept_as_is=False" in captured.err


def _load_session_start_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "deploy/cursor/hooks/ylang-session-start.py"
    )
    spec = importlib.util.spec_from_file_location("ylang_session_start_hook", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_session_start_exports_capture_edit_feedback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_session_start_module()
    monkeypatch.delenv("YLANG_CAPTURE_EDIT_FEEDBACK", raising=False)
    monkeypatch.delenv("YLANG_EDIT_FEEDBACK", raising=False)
    with (
        patch.object(
            module, "_load_ylang_mcp", return_value=("http://127.0.0.1/mcp", "tok")
        ),
        patch("sys.stdin", io.StringIO("")),
    ):
        module.main()
    env = json.loads(capsys.readouterr().out)["env"]
    assert env["YLANG_CAPTURE_EDIT_FEEDBACK"] == "1"
    assert env["YLANG_MCP_URL"] == "http://127.0.0.1/mcp"


def test_session_start_exports_correlation_from_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_session_start_module()
    payload = {
        "session_id": "sess-abc",
        "workspace_roots": ["/home/me/projects/ylang"],
    }
    with (
        patch.object(
            module, "_load_ylang_mcp", return_value=("http://127.0.0.1/mcp", "tok")
        ),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        module.main()
    env = json.loads(capsys.readouterr().out)["env"]
    assert env["YLANG_SESSION_ID"] == "sess-abc"
    assert env["YLANG_WORKSPACE"] == "ylang"


def test_correlation_from_payload_prefers_conversation_id(
    hook_module, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("YLANG_SESSION_ID", raising=False)
    monkeypatch.delenv("YLANG_LAST_TRACE_ID", raising=False)
    corr = hook_module._correlation_from_payload(
        {
            "conversation_id": "conv-123",
            "workspace_roots": ["/srv/ylang"],
        }
    )
    assert corr["session_id"] == "conv-123"
    assert corr["workspace"] == "ylang"
    assert corr["parent_trace_id"] is None


def test_correlation_reads_prior_trace_from_last_trace_file(
    hook_module, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "ylang-last-trace.json").write_text(
        json.dumps({"trace_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}),
        encoding="utf-8",
    )
    corr = hook_module._correlation_from_payload({"conversation_id": "c1"})
    assert corr["parent_trace_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_hook_passes_correlation_to_improve_prompt(
    hook_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    payload = {
        "prompt": "add dark mode toggle",
        "composer_mode": "agent",
        "conversation_id": "conv-xyz",
        "workspace_roots": ["/tmp/my-app"],
    }
    seen: list[dict[str, object]] = []

    async def fake_improve(**kwargs: object) -> dict[str, object]:
        seen.append(dict(kwargs))
        return {
            "improved": "Add a dark mode toggle to settings.",
            "original": "add dark mode toggle",
            "validated": True,
            "auto_apply_default": True,
            "cursor_mode": "agent",
            "mode_source": "explicit",
            "trace_id": "trace-1111-2222-3333-444444444444",
        }

    with (
        patch.object(
            hook_module,
            "_load_mcp_config",
            return_value=("http://127.0.0.1/mcp", "token"),
        ),
        patch.object(hook_module, "_call_improve_prompt", side_effect=fake_improve),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        hook_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out)["updated_input"]["prompt"].startswith("Add a dark")
    assert seen[0]["session_id"] == "conv-xyz"
    assert seen[0]["workspace"] == "my-app"
    last_trace = json.loads(
        (tmp_path / ".cursor" / "ylang-last-trace.json").read_text(encoding="utf-8")
    )
    assert last_trace["trace_id"] == "trace-1111-2222-3333-444444444444"
    sidecar = (tmp_path / ".cursor" / "ylang-improved-prompt.md").read_text(
        encoding="utf-8"
    )
    assert "session_id: `conv-xyz`" in sidecar
    assert "trace_id: `trace-1111-2222-3333-444444444444`" in sidecar

