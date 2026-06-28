# Ylang

Personal AI efficiency layer — Phase 1 is an [MCP](https://modelcontextprotocol.io) server over one shared core engine. Faces (MCP today, desktop gateway later) are thin adapters; business logic lives in `src/ylang/core` and is never duplicated in adapters.

## Requirements

- Python 3.12+

## Install

Use a virtual environment. Do **not** install with system `pip` on Linux (PEP 668 *externally-managed-environment*).

If you use **both Windows and WSL** on the same clone, create the venv in the environment you are using (Windows `.venv\Scripts\` vs Linux `.venv/bin/`). Do not activate a Windows venv from bash (e.g. avoid `source .../Scripts/activate` in WSL).

### WSL / Linux / macOS

From the repo root (WSL example: `/mnt/c/Users/you/source/ylang`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Ubuntu/Debian, `python3` is the default; optional: `sudo apt install python-is-python3` if you want the `python` command to mean Python 3.

### Windows (PowerShell or cmd)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## Run

Start the MCP server on stdio (used by Cursor and other MCP clients). With the venv activated:

```bash
python -m ylang
```

(WSL/Linux: use `python3 -m ylang` if `python` is not installed.)

On startup the server prints its storage path and registered tools to stderr, then waits for MCP traffic on stdin/stdout.

### Cursor MCP configuration

Add to `.cursor/mcp.json` (or your global MCP config). When developing from a checkout without installing, set `PYTHONPATH` so `ylang` resolves from `src/`:

```json
{
  "mcpServers": {
    "ylang": {
      "command": "python",
      "args": ["-m", "ylang"],
      "env": {
        "PYTHONPATH": "${workspaceFolder}/src"
      }
    }
  }
}
```

After `pip install -e .`, you can omit `PYTHONPATH`. Optionally set `YLANG_STORAGE_PATH` (see below) in `env`.

## MCP tools

| Tool | Description |
|------|-------------|
| `improve_prompt` | Propose-only structural prompt edits; returns `{original, improved, changes}` and never applies changes. |
| `save_template` | Save a new user template version to the local library. |
| `recall_template` | Fetch a template by id; optionally render with param values. |
| `list_templates` | List templates with latest-version metadata (filter by `source`: `seed`, `user`, or `learned`). |
| `remember` | Persist a user fact under a named scope (requires `ylang.core.memory`; see [docs/dead-code.md](docs/dead-code.md)). |
| `recall_usage` | Return raw usage rows for a time window (`last_hours`, `last_days`, or `since`/`until`). |

## Local-first and privacy

Ylang is local-first by default:

- **Storage:** SQLite at `~/.ylang/ylang.db`. Override with the `YLANG_STORAGE_PATH` environment variable (path to the database file).
- **Templates and usage:** Saved and read only from your local database. Ylang does not upload templates, facts, or usage history to any Ylang-operated cloud service.
- **Usage logging:** Every improver call and (when wired) core completion writes a row to the local `usage` table.
- **LLM providers:** Calls go to whatever models you configure via LiteLLM (OpenAI, Anthropic, Ollama, etc.). Provider traffic is governed by your API keys and provider policies, not by Ylang cloud storage.

## Project layout

```
src/ylang/
├── core/       # Shared engine (LiteLLM routing, completion, future memory)
├── improver/   # Propose-only structural text improvement
├── usage/      # SQLite usage store (write on every request)
├── library/    # Local versioned prompt template library
├── mcp/        # MCP server adapter (stdio, tool registration)
└── settings.py # Typed config (storage path, env vars)
```

## Development notes

- Improver is **propose-only**: it returns suggestions; auto-apply defaults are off for precision tools.
- Phase 1 scope only — no optimizer, provenance, GitHub/KB sources, or hosted team features.
- Unused or stub code is documented in [docs/dead-code.md](docs/dead-code.md) (audit only; nothing removed).
