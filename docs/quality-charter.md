# Code quality charter

Living principles for maintainability in Ylang (`ylang` ≥ v0.5.2). Soft limits — justify exceptions in code comments or this charter’s residual-debt section in [quality-loop.md](quality-loop.md).

## Principles

1. **Smallest change that fully satisfies the goal** — no drive-by refactors outside the task.
2. **Preserve public APIs** — MCP tools, gateway routes, CLI, and console URLs/behavior stay stable unless a change is required and documented.
3. **Thin adapters** — MCP, gateway, console, and CLI serialize I/O; domain logic lives in `core/`, `improver/`, `library/`, `usage/`.
4. **Behavior-preserving refactors** — keep HTML escaping (`html.escape`), fail-open improver/LLM fallbacks, and server-rendered console (no React rewrite).
5. **Docs match code** — update `docs/` when layout or operator-facing behavior changes.

## Soft limits

| Limit | Soft threshold | When exceeded |
|-------|----------------|---------------|
| Function body | ~80 LOC | Prefer helpers or a named pipeline step |
| File | ~500 LOC | Split by domain or justify (generated/static blobs count separately) |
| God-function (new/refactored) | ~120 LOC | Document residual exceptions in [quality-loop.md](quality-loop.md) |
| File (stretch goal) | ~600 LOC | Modular package preferred over one monolith |

Embedded CSS/JS should live under `console/static/` and be served with cache headers when practical.

## Config authority

Effective settings resolve **env (`Settings.load`) → runtime SQLite overrides → merge**. See [configuration.md](configuration.md#authority-order).

## Safety net

- `ruff check .` and `pytest -m "not llm_e2e"` before declaring a quality wave done.
- Static typecheck (`pyright`) in CI (non-blocking or blocking as configured in the workflow).
- Prefer typed exceptions / log+re-raise on hot paths; do not break LLM fallback `except` seams without tests.

## Contributing

See also [CONTRIBUTING.md](../CONTRIBUTING.md) and [development.md](development.md).
