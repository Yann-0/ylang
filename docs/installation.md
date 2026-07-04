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
