# ylang

Personal AI efficiency layer — MCP server (Phase 1).

## Requirements

- Python 3.12+

## Install

```bash
pip install -e .
```

## Run

```bash
python -m ylang
```

## Layout

- `src/ylang/core` — shared engine
- `src/ylang/improver` — propose-only text improvement
- `src/ylang/usage` — usage store (SQLite)
- `src/ylang/library` — local library
- `src/ylang/mcp` — MCP server adapter
