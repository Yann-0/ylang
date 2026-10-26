# On-prem qualification and CI migration

## Status and boundary

These files prepare an on-prem controller and scheduler. They do not install or
activate them. Existing GitHub workflows remain active until an administrator
separately approves and disables them. Removing workflow files in an unpublished
branch does not stop the existing schedule.

All qualification commands run on **stelsrv-d001**. GitHub is the source/review
system; it is not the CI controller or scheduler. Do not register a GitHub
self-hosted runner as a substitute. The quickcards runner is unrelated.

## Controller contract

`scripts/onprem_ci.py` accepts a local bare mirror, an operator-owned file
containing one full commit SHA, a verified offline wheelhouse, and a private runs
directory. Mirror ownership trust is scoped to the clone and its upload-pack\nsubprocess; no global Git trust entries are written. It never fetches a moving branch, calls a provider, refreshes sources,
promotes prompts, publishes artifacts externally, or deploys Ylang.

A nonblocking host lock serializes jobs. Each job gets its own checkout, venvs,
HOME, temporary storage, synthetic SQLite files, logs, and artifacts. Credentials
are excluded from the worker environment; an explicit empty Ylang env file
prevents production env-file discovery.

Required steps stop on a nonzero exit. Missing executables fail with 127 and
timeouts with 124. A failed or interrupted job cannot advance `last-success.json`.
An unchanged input signature reuses a verified previous success and wheel; it
does not claim a newly executed test run. The signature includes the source,
controller files, dependency manifest, Python, Node, and kernel identities.

The pipeline checks:

- Editable source installation from the wheelhouse and dependency consistency.
  Source tests retain their repository-fixture contract; the installed wheel is
  checked independently.
- `ruff check .`, `pyright`, and `pytest -m "not llm_e2e and not network"`.
- `mkdocs build --strict` with retained site output.
- Wheel build, duplicate-entry rejection, and inclusion of every tracked package file.
- A fresh runtime-only venv installed from the wheel and offline dependencies.
- Installed-package identity and alias-policy equivalence, MCP template/scoped-memory round trips, gateway
  health/authentication, and packaged console assets.

Live source contracts, Ollama smoke, paid evaluations, quality experiments,
publishing, and deployment require their own approved scope.

## Dependency intake

Prepare a reviewed set of wheels for the declared runtime, dev, docs, and build
requirements on the server, including requirements returned by the build
backend's editable-build hook (Hatchling currently requests editables~=0.3). Pin versions during intake. `wheels.json` maps every
wheel basename to its SHA-256. Only the manifest and its regular wheel files are
allowed; source archives, extra directories, missing, changed, or symlinked files fail
preflight. Keep the directory and manifest root-owned and read-only to CI.

The preparation evidence retains the exact pinned intake requirements and wheel
hashes. Intake may download approved dependencies; the job itself uses
`--no-index` and never resolves packages from the internet. Hashes identify
contents; operator review establishes which dependency snapshot is approved.

## Reviewable activation sequence

The following steps need separate approval. They were not executed by preparing
this branch.

### 1. Stop cloud execution before publication

Recheck workflow identities and active runs first. After approval, disable all
three workflows, then verify their disabled state:

```bash
gh workflow disable ci.yml --repo Yann-0/ylang
gh workflow disable llm-e2e.yml --repo Yann-0/ylang
gh workflow disable pages.yml --repo Yann-0/ylang
gh api repos/Yann-0/ylang/actions/workflows
```

Check for in-flight runs and request approval before canceling any. Keep Actions
disabled during migration; deleting these workflow files takes effect in source
only after separate publication/merge approval.

### 2. Install the local account and files

Review the dedicated account first; never reuse an account with production,
sudo, docker-group, or provider-secret access.

```bash
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin ylang-ci
sudo install -d -m 0750 -o root -g ylang-ci \
  /usr/local/libexec/ylang-ci /usr/local/share/doc/ylang \
  /etc/ylang-ci /var/cache/ylang-ci/wheels /var/lib/ylang-ci
sudo install -d -m 0700 -o ylang-ci -g ylang-ci /var/lib/ylang-ci/runs
sudo install -m 0640 -o root -g ylang-ci \
  scripts/onprem_ci.py scripts/ci_guard.py scripts/ci_smoke.py \
  /usr/local/libexec/ylang-ci/
sudo install -m 0640 -o root -g ylang-ci docs/ci.md /usr/local/share/doc/ylang/ci.md
```

Provision a separately approved local bare mirror at
`/var/lib/ylang-ci/repository.git`, the reviewed wheelhouse at
`/var/cache/ylang-ci/wheels`, and the exact approved SHA at
`/etc/ylang-ci/approved-commit`. These inputs must be root-owned,
group-readable by `ylang-ci`, and not writable by that account. Do not copy
production data, env files, credentials, or the production venv.

Install the templates only after those inputs and permissions are verified:

```bash
sudo install -m 0644 deploy/ylang-ci.service deploy/ylang-ci.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

The service limits CPU to four cores, memory to 6 GiB, and tasks to 256. It removes
capabilities, denies network address families except Unix sockets, uses a private
network, protects system/home paths, and blocks production Ylang paths. Its only
persistent writable path is the private runs directory.

Python audit guards provide additional protection for direct/manual checks.
They are not an OS sandbox. The systemd restrictions must be qualified under
the dedicated account after installation; static verification alone does not
establish them.

### 3. Qualify the installed service before scheduling

After explicit execution approval:

```bash
sudo systemctl start ylang-ci.service
systemctl status ylang-ci.service --no-pager
journalctl -u ylang-ci.service --no-pager
```

Require a passing manifest, wheel hash, and installed smoke evidence. Verify
that the account cannot read production env/data, cannot use the network, and
cannot write the mirror, wheelhouse, or approved-commit file. Exercise a failed
command and inspect the failed unit/job; do not accept skipped gates as passes.

Only after separate timer activation approval:

```bash
sudo systemctl enable --now ylang-ci.timer
systemctl list-timers ylang-ci.timer
```

The timer checks hourly with up to five minutes of jitter. Unchanged approved
inputs do not repeat the full build. Changing the approved SHA or wheelhouse is
an operator action; there is no remote automatic promotion.

### 4. Publish separately

Push/PR, merge, release, documentation hosting, and application deployment each
retain their approval boundary. Keep the cloud workflow retirement diff in the
published branch. A local passing job does not deploy the production service.

## Evidence and recovery

Each run retains `manifest.json`, logs, JUnit output, the built documentation,
and the qualified wheel. The manifest identifies the source, controller,
dependencies, runtime, command, exit code, timestamps, and artifact hash.
Retention is manual until an explicit retention policy is approved; no cleanup
scheduler is installed by this change.

Failed and interrupted directories stay available for diagnosis. A RUNNING
manifest from an interrupted process is not a pass. Re-run only after inspecting
the failure; never edit evidence into a passing result.

To suspend scheduling after approval:

```bash
sudo systemctl disable --now ylang-ci.timer
```

Stopping an active service is a separate operation. Preserve logs and artifacts.
Controller rollback restores the previous root-owned controller and approved
input files; it does not change the application or production database.

Historical workflow/closure reports describe their dated runs. Current
readiness comes from the current manifest. Provider execution, source
compatibility, prompt quality improvement, and production approval remain
separate flags.
