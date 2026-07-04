# Installation

Ylang requires **Python 3.12 or newer**. All dependencies are declared in `pyproject.toml`.

## Virtual environment (required)

Do **not** install with system `pip` on Linux distributions that enforce PEP 668 (*externally-managed-environment*). Always use a virtual environment.

If you use **both Windows and WSL** on the same clone, create the venv in the environment you are using. Do not activate a Windows venv from bash.

### Linux / macOS / WSL

```bash
git clone https://github.com/Yann-0/ylang.git
cd ylang/app
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Ubuntu/Debian, `python3` is the default interpreter. Optionally install `python-is-python3` if you want the `python` command to mean Python 3.

### Windows (PowerShell)

```powershell
git clone https://github.com/Yann-0/ylang.git
cd ylang/app
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

### Development dependencies

For tests and linting:

```bash
pip install -e ".[dev]"
```

## Verify installation

```bash
python -c "import ylang; print(ylang.__version__)"
python -m ylang    # starts MCP server on stdio — press Ctrl+C to stop
```

There is no `--help` flag; `python -m ylang` always starts the server. The process prints connection details to **stderr** and waits for MCP traffic on stdin/stdout (stdio transport).

## CLI (`ylang` command)

`pip install -e .` installs a **`ylang`** console script into the active venv (`app/.venv/bin/ylang`). It is **not** on your shell `PATH` until you activate the venv or use a wrapper.

### From `app/` (development)

```bash
cd app
source .venv/bin/activate
ylang usage digest --last-days 7
ylang patterns apply --help
```

Same without activation:

```bash
app/.venv/bin/ylang usage digest --last-days 7
```

### Workspace layout (`/srv/ylang`)

This server keeps the git tree in **`app/`** and often a second venv at **`/srv/ylang/.venv`** for systemd (`python -m ylang`). The CLI wrapper prefers `app/.venv`, then falls back to the root venv:

```bash
# One-time: put `ylang` on PATH (pick one)
ln -sf /srv/ylang/app/deploy/ylang-cli ~/.local/bin/ylang
# or
mkdir -p /srv/ylang/bin && ln -sf ../app/deploy/ylang-cli /srv/ylang/bin/ylang
export PATH="/srv/ylang/bin:$PATH"   # add to ~/.bashrc / ~/.zshrc to persist

ylang patterns apply --help
```

For CLI commands that read the **same SQLite file as the HTTP service**, load the service env first:

```bash
set -a && source /srv/ylang/ylang.env && set +a
ylang usage digest --last-days 7
```

The `ylang` system user owns `/srv/ylang/data/`. Run **`sudo deploy/setup-cli-access.sh`** once as root (sets data **`770`**, `ylang.env` **`640`**, group **`ylang`**). **Log out/in** for permanent group membership, or run CLI via `sg ylang -c '…'` — `newgrp ylang` alone does not apply to the next command in the same shell. See [deployment.md](deployment.md#shared-cli-access).

## First run

1. **Set at least one LLM provider key** (or configure a local Ollama fallback). See [configuration.md](configuration.md).
2. Start the server:

   ```bash
   python -m ylang
   ```

3. Configure your MCP client. See [Cursor integration](cursor-integration.md) or the [MCP tools reference](mcp-tools.md).

On first startup, Ylang creates a SQLite database at `~/.ylang/ylang.db` (override with `YLANG_STORAGE_PATH`).

## Install without cloning (future)

When published to PyPI:

```bash
pip install ylang
```

Phase 1 is distributed from source via `pip install -e .` from the repository.

## Troubleshooting

### `externally-managed-environment`

Use a venv as shown above. Do not use `pip install --break-system-packages`.

### `ModuleNotFoundError: No module named 'ylang'`

- Ensure the venv is activated.
- Run `pip install -e .` from the repository root.
- For Cursor without install, set `PYTHONPATH` to `${workspaceFolder}/src` in MCP config.

### SQLite permission errors

If you see `SQLite storage is not writable`, check directory ownership and permissions on `YLANG_STORAGE_PATH`. See [deployment.md](deployment.md) for the systemd `ylang` user layout.

### Port already in use (HTTP transport)

Only one process can bind to `YLANG_PORT` (default 8787). Stop the existing instance or change the port.

## Next steps

- [Configuration](configuration.md) — API keys, model prioritization, routing, storage path
- [Cursor integration](cursor-integration.md) — hooks and auto prompt improvement
- [MCP tools reference](mcp-tools.md) — tool API
