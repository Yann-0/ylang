# ylang

Personal AI efficiency layer — MCP server (Phase 1).

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

With the venv activated:

```bash
python -m ylang
```

(WSL/Linux: use `python3 -m ylang` if `python` is not installed.)

The MCP server starts on stdio. Startup details are printed to **stderr** (storage path, tools, ready message).

## Layout

- `src/ylang/core` — shared engine
- `src/ylang/improver` — propose-only text improvement
- `src/ylang/usage` — usage store (SQLite)
- `src/ylang/library` — local library
- `src/ylang/mcp` — MCP server adapter
