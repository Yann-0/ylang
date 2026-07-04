# Development

Guide for contributors and maintainers working on the Ylang codebase.

## Setup

```bash
git clone https://github.com/Yann-0/ylang.git
cd ylang
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Project layout

```
ylang/
├── src/ylang/           # Application source
├── tests/               # Unit and integration tests
│   └── integration/     # MCP and e2e tests
├── deploy/              # systemd unit, Cursor hook templates
├── scripts/             # Maintenance and e2e scripts
├── docs/                # Documentation (you are here)
├── pyproject.toml       # Package metadata and tool config
└── README.md            # Project landing page
```

## Commands

| Command | Purpose |
|---------|---------|
| `pytest` | Run all tests |
| `pytest tests/test_engine.py -v` | Run a single test file |
| `ruff check .` | Lint |
| `ruff format .` | Format |
| `python -m ylang` | Start MCP server (stdio) |

There is no separate `typecheck` script — use your editor or `pyright` if desired. Ruff targets Python 3.12.

## Testing

Tests use **pytest** with `asyncio_mode = auto` for MCP integration tests.

### Fixtures (`tests/conftest.py`)

- `db_path` — temporary SQLite file
- `ylang_deps` — wired `YlangDeps` matching production MCP startup
- MCP server fixtures for integration tests

### Integration tests

| File | Coverage |
|------|----------|
| `tests/integration/test_mcp_tools.py` | MCP tool registration and handlers |
| `tests/integration/test_improve_prompt_e2e.py` | End-to-end improver (may call LLM if keys set) |

### Running with coverage (optional)

```bash
pip install pytest-cov
pytest --cov=ylang --cov-report=term-missing
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/e2e_improve_prompt.py` | Manual improver e2e against live LLM |
| `scripts/import-public-prompts.sh` | Shell wrapper for public prompt import |
| `scripts/populate-public-prompts-via-mcp.py` | Import via MCP tool |

## Architecture rules (enforced by convention)

1. **Faces are thin** — `mcp/tools.py` only serializes; no business logic.
2. **One engine** — all LLM calls go through `Engine.complete()`.
3. **Propose-only improver** — never auto-apply to user files from server code.
4. **Phase 1 scope** — see `.cursor/rules/00-project.mdc` and [architecture.md](architecture.md).

## Adding an MCP tool

1. Implement domain logic in the appropriate package (`library/`, `improver/`, etc.).
2. Add a thin handler in `mcp/tools.py` inside `register_tools()`.
3. Add the tool name to `_TOOL_NAMES` in `mcp/server.py`.
4. Add tests in `tests/integration/test_mcp_tools.py`.
5. Document in [mcp-tools.md](mcp-tools.md).

## Adding a dependency

Phase 1 policy: **no new runtime dependency without discussion**. Update `pyproject.toml` and explain why in the PR.

Current runtime deps: `mcp`, `litellm`, `pydantic`. HTTP transport also requires `uvicorn` (pulled in by MCP extras).

## Importer CLI

Separate from the MCP server:

```bash
python -m ylang.importer --help
```

Imports public prompt CSVs into the library database. Tested in `tests/test_importer.py` (if present) and callable via MCP `import_public_prompts`.

## Local database inspection

```bash
sqlite3 ~/.ylang/ylang.db ".tables"
sqlite3 ~/.ylang/ylang.db "SELECT activity, model_used, cost FROM usage ORDER BY id DESC LIMIT 10;"
```

See [database-schema.md](database-schema.md) for table definitions.

## Release checklist

- [ ] `pytest` and `ruff check .` pass
- [ ] Version bumped in `src/ylang/__init__.py` and `pyproject.toml` if releasing
- [ ] [mcp-tools.md](mcp-tools.md) and [configuration.md](configuration.md) updated for behavior changes
- [ ] [CHANGELOG](CHANGELOG.md) entry (when maintaining a changelog)

## Related docs

- [CONTRIBUTING.md](../CONTRIBUTING.md) — PR process
- [Architecture](architecture.md) — module design
- [Dead code audit](dead-code.md) — unused symbols (audit only)
