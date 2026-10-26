"""Failure and isolation contracts for the on-prem qualification controller."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest


def controller() -> ModuleType:
    """Load the standalone controller without running its CLI."""
    path = Path(__file__).resolve().parents[1] / "scripts/onprem_ci.py"
    spec = importlib.util.spec_from_file_location("onprem_ci", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("command,exit_code", [
    ([sys.executable, "-c", "raise SystemExit(23)"], 23),
    (["/nonexistent-ylang-ci-command"], 127),
])
def test_failed_command_records_nonzero_exit(
    tmp_path: Path, command: list[str], exit_code: int,
) -> None:
    """A failed or absent executable must produce a failed retained step."""
    module = controller()
    (tmp_path / "logs").mkdir()
    manifest: dict = {"steps": []}
    with pytest.raises(RuntimeError, match=f"exit code {exit_code}"):
        module.run_step(manifest, tmp_path, "failure", command, tmp_path, dict(os.environ))
    saved = json.loads((tmp_path / "manifest.json").read_text())
    assert saved["steps"][0]["exit_code"] == exit_code
    assert saved["steps"][0]["status"] == "FAIL"
    assert (tmp_path / "logs/failure.log").exists()


def test_timeout_is_failed_and_bounded(tmp_path: Path) -> None:
    """A timed-out process group must stop and retain exit code 124."""
    module = controller()
    (tmp_path / "logs").mkdir()
    manifest: dict = {"steps": []}
    with pytest.raises(RuntimeError, match="exit code 124"):
        module.run_step(
            manifest, tmp_path, "timeout",
            [sys.executable, "-c", "import time; time.sleep(60)"],
            tmp_path, dict(os.environ), timeout=0.1,
        )
    assert manifest["steps"][0]["elapsed_seconds"] < 5


def test_second_controller_cannot_take_lock(tmp_path: Path) -> None:
    """A competing controller must fail immediately instead of sharing state."""
    module = controller()
    with module.exclusive_lock(tmp_path / "lock"):
        with pytest.raises(BlockingIOError):
            with module.exclusive_lock(tmp_path / "lock"):
                pytest.fail("second controller acquired the lock")


@pytest.mark.parametrize("value", ["main", "HEAD~1", "a" * 40 + "\n" + "b" * 40, ""])
def test_moving_or_multiple_refs_are_rejected(tmp_path: Path, value: str) -> None:
    """Only one immutable full SHA may select project code."""
    path = tmp_path / "approved-commit"
    path.write_text(value)
    with pytest.raises(ValueError, match="full 40-character SHA"):
        controller().approved_commit(path)


@pytest.mark.parametrize("change", ["tamper", "extra", "missing", "symlink", "sdist", "zip", "directory"])
def test_wheelhouse_changes_fail_closed(tmp_path: Path, change: str) -> None:
    """Dependency changes must be detected before a project command runs."""
    module = controller()
    wheel = tmp_path / "fixture-1-py3-none-any.whl"
    wheel.write_bytes(b"dependency fixture")
    expected = {wheel.name: hashlib.sha256(wheel.read_bytes()).hexdigest()}
    (tmp_path / "wheels.json").write_text(json.dumps(expected))
    module.verify_wheelhouse(tmp_path)
    if change == "tamper":
        wheel.write_bytes(b"changed")
    elif change == "extra":
        (tmp_path / "other.whl").write_bytes(b"extra")
    elif change == "missing":
        wheel.unlink()
    elif change == "sdist":
        (tmp_path / "fixture-2.tar.gz").write_bytes(b"unmanifested source")
    elif change == "zip":
        (tmp_path / "fixture-2.zip").write_bytes(b"unmanifested source")
    elif change == "directory":
        (tmp_path / "unmanifested-source").mkdir()
    else:
        target = tmp_path / "target"
        wheel.rename(target)
        wheel.symlink_to(target)
    with pytest.raises(ValueError):
        module.verify_wheelhouse(tmp_path)


def test_pipeline_failure_preserves_previous_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed job must not advance the successful qualification pointer."""
    module = controller()
    source = tmp_path / "fixture"
    source.mkdir()
    for command in (
        ["git", "init", str(source)],
        ["git", "-C", str(source), "add", "."],
    ):
        subprocess.run(command, check=True, capture_output=True)
    (source / "README").write_text("synthetic fixture\n")
    subprocess.run(["git", "-C", str(source), "add", "README"], check=True)
    subprocess.run([
        "git", "-C", str(source), "-c", "user.name=CI Fixture",
        "-c", "user.email=ci-fixture@example.invalid", "commit", "-m", "fixture",
    ], check=True, capture_output=True)
    sha = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True,
    ).strip()
    repository = tmp_path / "mirror.git"
    subprocess.run(["git", "clone", "--bare", str(source), str(repository)], check=True, capture_output=True)
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    wheel = wheels / "fixture.whl"
    wheel.write_bytes(b"fixture")
    (wheels / "wheels.json").write_text(json.dumps({
        wheel.name: hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }))
    approved = tmp_path / "approved"
    approved.write_text(sha + "\n")
    runs = tmp_path / "runs"
    runs.mkdir()
    pointer = runs / "last-success.json"
    original = '{"signature":"previous","manifest":"previous"}\n'
    pointer.write_text(original)

    def fail_pipeline(*args: object) -> None:
        """Inject a failure after controller preflight succeeds."""
        raise RuntimeError("deliberate qualification failure")

    monkeypatch.setattr(module, "qualify", fail_pipeline)
    monkeypatch.setattr(module.socket, "gethostname", lambda: "stelsrv-d001")
    monkeypatch.setattr(sys, "argv", [
        "onprem_ci.py", "--repository", str(repository),
        "--wheelhouse", str(wheels), "--runs-dir", str(runs),
        "--approved-commit-file", str(approved),
    ])
    assert module.main() == 1
    assert pointer.read_text() == original
    failed = list(runs.glob("*/manifest.json"))
    assert len(failed) == 1
    assert json.loads(failed[0].read_text())["status"] == "FAIL"


def test_wrong_host_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The qualification CLI must refuse an unapproved execution host."""
    module = controller()
    monkeypatch.setattr(module.socket, "gethostname", lambda: "other-host")
    monkeypatch.setattr(sys, "argv", [
        "onprem_ci.py", "--repository", str(tmp_path / "mirror"),
        "--wheelhouse", str(tmp_path / "wheels"), "--runs-dir", str(tmp_path / "runs"),
        "--approved-commit-file", str(tmp_path / "approved"),
    ])
    with pytest.raises(ValueError, match="restricted to stelsrv-d001"):
        module.main()
    assert not (tmp_path / "runs").exists()


def test_candidate_has_no_github_actions_workflows() -> None:
    """Source publication must not introduce a hosted controller or scheduler."""
    workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
    assert not list(workflows.glob("*.yml"))
    assert not list(workflows.glob("*.yaml"))


def test_fresh_python_blocks_network_and_external_sqlite(tmp_path: Path) -> None:
    """A fresh worker must deny real network setup and out-of-run databases."""
    module = controller()
    (tmp_path / "logs").mkdir()
    (tmp_path / "home").mkdir()
    (tmp_path / "tmp").mkdir()
    environment = module.private_environment(tmp_path, tmp_path / "wheels")
    outside = tmp_path.parent / (tmp_path.name + "-outside.db")
    program = (
        "import json,socket,sqlite3,sys; "
        "assert hasattr(sys.modules['sitecustomize'],'guard'); "
        "blocked=[]\n"
        "for name,call in [('network',lambda:socket.getaddrinfo('127.0.0.1',8787)),"
        f"('database',lambda:sqlite3.connect({str(outside)!r}))]:\n"
        " try: call()\n"
        " except PermissionError: blocked.append(name)\n"
        " else: raise AssertionError(name+' was allowed')\n"
        "print(json.dumps(blocked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["network", "database"]
    assert not outside.exists()


def test_cross_owner_mirror_trust_reaches_upload_pack(tmp_path: Path) -> None:
    """Cross-owner cloning must work without persistent Git trust or hardlinks."""
    module = controller()
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    subprocess.run(["git", "init", str(fixture)], check=True, capture_output=True)
    (fixture / "README").write_text("synthetic mirror fixture")
    subprocess.run(["git", "-C", str(fixture), "add", "README"], check=True)
    subprocess.run([
        "git", "-C", str(fixture), "-c", "user.name=CI Fixture",
        "-c", "user.email=ci-fixture@example.invalid", "commit", "-m", "fixture",
    ], check=True, capture_output=True)
    mirror = tmp_path / "mirror.git"
    subprocess.run(["git", "clone", "--bare", str(fixture), str(mirror)], check=True, capture_output=True)
    checkout = tmp_path / "checkout"
    environment = {
        **os.environ, "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TEST_ASSUME_DIFFERENT_OWNER": "true",
    }
    result = subprocess.run(
        module.local_clone_command(mirror, checkout),
        env=environment, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    source_objects = [p for p in (mirror / "objects").glob("*/*") if p.is_file()]
    assert source_objects
    for original in source_objects:
        copied = checkout / ".git/objects" / original.relative_to(mirror / "objects")
        assert copied.read_bytes() == original.read_bytes()
        assert copied.stat().st_ino != original.stat().st_ino
    assert not (tmp_path / ".gitconfig").exists()
