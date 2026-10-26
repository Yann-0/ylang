"""Run approved Ylang commits locally from a verified offline wheelhouse."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import socket
import subprocess
import sys
import time
import tomllib
import uuid


def write_json(path: Path, value: object) -> None:
    """Atomically replace a private JSON record."""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def digest(path: Path) -> str:
    """Hash a file without loading it into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def approved_commit(path: Path) -> str:
    """Require one immutable full SHA, never an executable ref expression."""
    commit = path.read_text().strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("approved-commit must contain exactly one full 40-character SHA")
    return commit


def verify_wheelhouse(path: Path) -> str:
    """Reject missing, extra or changed wheels before executing project code."""
    if (path / "wheels.json").is_symlink() or any(p.is_symlink() for p in path.glob("*.whl")):
        raise ValueError("wheelhouse symlinks are not permitted")
    expected = json.loads((path / "wheels.json").read_text())
    actual = {p.name for p in path.glob("*.whl")}
    if not expected or actual != set(expected):
        raise ValueError("wheelhouse inventory mismatch")
    for name, checksum in expected.items():
        if Path(name).name != name or not name.endswith(".whl"):
            raise ValueError("invalid wheelhouse filename")
        if digest(path / name) != checksum:
            raise ValueError("wheelhouse checksum mismatch: " + name)
    return digest(path / "wheels.json")


@contextmanager
def exclusive_lock(path: Path):
    """Allow only one controller using this state directory."""
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def run_step(
    manifest: dict, run: Path, name: str, command: list[str],
    cwd: Path, env: dict[str, str], timeout: float = 300,
) -> None:
    """Retain a command's real exit code and stop the job on failure."""
    log = run / "logs" / (name + ".log")
    step = {
        "name": name, "command": command, "cwd": str(cwd),
        "started_at": datetime.now(timezone.utc).isoformat(), "log": str(log),
    }
    began = time.monotonic()
    with log.open("w") as output:
        output.write("COMMAND " + json.dumps(command) + "\n")
        output.flush()
        try:
            process = subprocess.Popen(
                command, cwd=cwd, env=env, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                code = 124
        except OSError as error:
            output.write(str(error) + "\n")
            code = 127
    step.update(
        exit_code=code, status="PASS" if code == 0 else "FAIL",
        finished_at=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=round(time.monotonic() - began, 3),
    )
    manifest["steps"].append(step)
    write_json(run / "manifest.json", manifest)
    print(json.dumps(step), flush=True)
    if code:
        raise RuntimeError(f"{name} failed with exit code {code}; see {log}")


def private_environment(run: Path, wheelhouse: Path) -> dict[str, str]:
    """Exclude inherited credentials and direct all state into this run."""
    (run / "empty.env").write_text("# No production settings.\n")
    guard = run / "guard"
    guard.mkdir()
    shutil.copyfile(Path(__file__).with_name("ci_guard.py"), guard / "sitecustomize.py")
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
        "HOME": str(run / "home"), "TMPDIR": str(run / "tmp"),
        "XDG_CACHE_HOME": str(run / "home/.cache"),
        "PYTHONPYCACHEPREFIX": str(run / "tmp/pycache"),
        "PYTHONPATH": str(guard), "YLANG_CI_RUN": str(run),
        "YLANG_ENV_FILE": str(run / "empty.env"),
        "YLANG_STORAGE_PATH": str(run / "synthetic.db"), "YLANG_TRANSPORT": "stdio",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True", "OTEL_SDK_DISABLED": "true",
        "DO_NOT_TRACK": "1", "PIP_CONFIG_FILE": "/dev/null",
        "PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(wheelhouse),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }



def local_clone_command(repository: Path, source: Path) -> list[str]:
    """Trust only this local mirror inside Git's upload-pack subprocess."""
    upload_pack = shlex.join([
        "/usr/bin/git", "-c", f"safe.directory={repository}", "upload-pack",
    ])
    return [
        "git", "-c", f"safe.directory={repository}", "clone",
        "--no-hardlinks", "--no-checkout", "--upload-pack=" + upload_pack,
        str(repository), str(source),
    ]


def qualify(manifest: dict, run: Path, repository: Path, wheelhouse: Path) -> None:
    """Build, test and install one immutable source tree without network access."""
    env = private_environment(run, wheelhouse)
    source = run / "source"
    run_step(manifest, run, "checkout-clone", local_clone_command(repository, source), run, env)
    run_step(manifest, run, "checkout-commit", [
        "git", "checkout", "--detach", manifest["commit"],
    ], source, env)
    metadata = tomllib.loads((source / "pyproject.toml").read_text())
    run_step(manifest, run, "create-venv", [
        sys.executable, "-m", "venv", str(source / ".venv"),
    ], source, env)
    python = str(source / ".venv/bin/python")
    env["PATH"] = str(source / ".venv/bin") + ":" + env["PATH"]
    pip = [python, "-m", "pip"]
    run_step(manifest, run, "build-dependencies", [
        *pip, "install", "--no-index", "--find-links", str(wheelhouse),
        *metadata["build-system"]["requires"],
    ], source, env)
    backend = metadata["build-system"]["build-backend"]
    hook = (
        "import importlib,subprocess,sys; "
        "backend=importlib.import_module(sys.argv[1]); "
        "requires=getattr(backend,'get_requires_for_build_editable',lambda:[])(); "
        "print('Editable build requirements:',requires,flush=True); "
        "subprocess.run([sys.executable,'-m','pip','install','--no-index',"
        "'--find-links',sys.argv[2],*requires],check=True) if requires else None"
    )
    run_step(manifest, run, "editable-build-dependencies", [
        python, "-c", hook, backend, str(wheelhouse),
    ], source, env)
    run_step(manifest, run, "install-project", [
        *pip, "install", "--no-index", "--find-links", str(wheelhouse),
        "--no-build-isolation", "-e", ".[dev,docs]",
    ], source, env)
    run_step(manifest, run, "dependency-check", [*pip, "check"], source, env)
    run_step(manifest, run, "dependency-identity", [*pip, "list", "--format=json"], source, env)
    run_step(manifest, run, "ruff", [python, "-m", "ruff", "check", "."], source, env)
    run_step(manifest, run, "pyright", [python, "-m", "pyright"], source, env)
    run_step(manifest, run, "pytest", [
        python, "-m", "pytest", "-p", "pytest_asyncio.plugin",
        "-m", "not llm_e2e and not network",
        "--basetemp", str(run / "tmp/pytest"),
        "-o", "cache_dir=" + str(run / "tmp/pytest-cache"),
        "--junitxml", str(run / "artifacts/pytest.xml"),
    ], source, env, timeout=900)
    run_step(manifest, run, "mkdocs", [
        python, "-m", "mkdocs", "build", "--strict",
        "--site-dir", str(run / "artifacts/site"),
    ], source, env)
    wheels = run / "artifacts/wheels"
    wheels.mkdir()
    run_step(manifest, run, "wheel-build", [
        *pip, "wheel", "--no-deps", "--no-index",
        "--no-build-isolation", "--wheel-dir", str(wheels), ".",
    ], source, env)
    built = list(wheels.glob("*.whl"))
    if len(built) != 1:
        raise ValueError("expected exactly one built wheel")
    import zipfile
    with zipfile.ZipFile(built[0]) as archive:
        names = archive.namelist()
        tracked = subprocess.check_output(
            ["git", "ls-files", "src/ylang"], cwd=source, env=env, text=True,
        ).splitlines()
        if len(names) != len(set(names)) or set(p[4:] for p in tracked) - set(names):
            raise ValueError("wheel is missing tracked package files or has duplicate entries")
    manifest["wheel"] = {"filename": built[0].name, "sha256": digest(built[0])}
    smoke = run / "smoke"
    smoke.mkdir()
    smoke_python = str(smoke / ".venv/bin/python")
    run_step(manifest, run, "smoke-venv", [
        sys.executable, "-m", "venv", str(smoke / ".venv"),
    ], smoke, env)
    run_step(manifest, run, "smoke-install", [
        smoke_python, "-m", "pip", "install", "--no-index",
        "--find-links", str(wheelhouse), str(built[0]),
    ], smoke, env)
    run_step(manifest, run, "smoke-dependencies", [
        smoke_python, "-m", "pip", "check",
    ], smoke, env)
    run_step(manifest, run, "installed-smoke", [
        smoke_python, str(Path(__file__).with_name("ci_smoke.py").resolve()),
        metadata["project"]["version"], str(source / "deploy/ylang.models.json"),
    ], smoke, env)


def main() -> int:
    """Serialize approved local jobs and publish success only after every gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--approved-commit-file", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if socket.gethostname().split(".")[0] != "stelsrv-d001":
        raise ValueError("qualification is restricted to stelsrv-d001")
    repository, wheelhouse, runs = (
        args.repository.resolve(), args.wheelhouse.resolve(), args.runs_dir.resolve(),
    )
    for left, right in ((repository, runs), (wheelhouse, runs), (repository, wheelhouse)):
        if left == right or left.is_relative_to(right) or right.is_relative_to(left):
            raise ValueError("repository, wheelhouse and runs must be separate directories")
    commit = approved_commit(args.approved_commit_file)
    wheelhouse_hash = verify_wheelhouse(wheelhouse)
    if args.approved_commit_file.resolve().is_relative_to(runs):
        raise ValueError("approved-commit file must be outside the writable runs directory")
    result = subprocess.check_output(
        ["git", "-c", f"safe.directory={repository}", "-C", str(repository),
         "rev-parse", "--is-bare-repository"], text=True,
    ).strip()
    if result != "true":
        raise ValueError("repository must be a local bare mirror")
    kind = subprocess.check_output(
        ["git", "-c", f"safe.directory={repository}", "-C", str(repository),
         "cat-file", "-t", commit], text=True,
    ).strip()
    if kind != "commit":
        raise ValueError("approved SHA must identify a commit")
    controller_hashes = {
        name: digest(Path(__file__).with_name(name))
        for name in ("onprem_ci.py", "ci_guard.py", "ci_smoke.py")
    }
    node_version = subprocess.check_output(["node", "--version"], text=True).strip()
    runtime = {"python": sys.version, "node": node_version, "kernel": os.uname().release}
    signature = hashlib.sha256(json.dumps(
        [commit, wheelhouse_hash, controller_hashes, runtime], sort_keys=True,
    ).encode()).hexdigest()
    runs.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(runs / ".controller.lock"):
        success = runs / "last-success.json"
        if success.exists():
            previous = json.loads(success.read_text())
            if previous.get("signature") == signature:
                evidence = Path(previous["manifest"]).resolve()
                if not evidence.is_relative_to(runs):
                    raise ValueError("previous success evidence is outside runs directory")
                completed = json.loads(evidence.read_text())
                wheel = completed["wheel"]
                if Path(wheel["filename"]).name != wheel["filename"]:
                    raise ValueError("invalid previous artifact filename")
                artifact = evidence.parent / "artifacts/wheels" / wheel["filename"]
                if completed.get("status") != "PASS" or digest(artifact) != wheel["sha256"]:
                    raise ValueError("previous success evidence or artifact is invalid")
                print(json.dumps({"status": "UNCHANGED", "previous_success": previous}), flush=True)
                return 0
        run = runs / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
        run.mkdir()
        for name in ("logs", "home", "tmp", "artifacts"):
            (run / name).mkdir()
        manifest = {
            "status": "RUNNING", "commit": commit, "host": socket.gethostname(),
            "runtime": runtime, "wheelhouse_manifest_sha256": wheelhouse_hash,
            "controller_hashes": controller_hashes, "signature": signature,
            "started_at": datetime.now(timezone.utc).isoformat(), "steps": [],
            "scope": "Offline qualification only; no provider/source calls or deployment.",
        }
        write_json(run / "manifest.json", manifest)
        try:
            qualify(manifest, run, repository, wheelhouse)
            if verify_wheelhouse(wheelhouse) != wheelhouse_hash:
                raise ValueError("wheelhouse changed during the run")
            manifest["status"] = "PASS"
        except Exception as error:
            manifest.update(status="FAIL", error=str(error))
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(run / "manifest.json", manifest)
        if manifest["status"] == "PASS":
            write_json(success, {"signature": signature, "manifest": str(run / "manifest.json")})
        print(json.dumps({"status": manifest["status"], "manifest": str(run / "manifest.json")}), flush=True)
        return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
