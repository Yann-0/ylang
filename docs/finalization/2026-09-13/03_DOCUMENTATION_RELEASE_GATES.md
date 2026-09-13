# 03 — Documentation and release gates

## Documentation map (updated this closure)

| Surface | Path |
|---------|------|
| Operator | `docs/prompt-intelligence.md` |
| Evaluation | `docs/evaluation-methodology.md` |
| CLI | `docs/cli.md` |
| Portal | `docs/portal.md` |
| Schema | `docs/database-schema.md` (migration 16) |
| Architecture | `docs/architecture.md` |
| Configuration | `docs/configuration.md` |
| Deployment | `docs/deployment.md` |
| MCP | `docs/mcp-tools.md` |
| README / changelog | `README.md`, `CHANGELOG.md` |
| Strategy (marked superseded) | `docs/strategy/YLANG_*_20260912.md` |
| Control plane | `docs/control-plane-evolution/04_EVALUATION_MODEL.md` |
| This package | `docs/finalization/2026-09-13/` |

## Quality gates (blocking)

```text
ruff check .                              PASS required
pyright                                   PASS required
pytest -m "not llm_e2e and not network"   PASS required
mkdocs build --strict                     PASS required
```

## Separate checks (non-blocking for LIBRARY_READY)

```text
YLANG_NETWORK_TESTS=1 pytest -m network     live source contracts
--mode execute --authorize-paid            paid provider; operator budget
```

## Release policy

Do **not** publish a release, change default enablement of sources, or push
without explicit authorization. Version remains `0.7.0` until a release is
requested. Changes sit in Unreleased.

## Rollback

- `git checkout` the previous SHA; SQLite migration 16 is additive
- Disable sources; inspect evaluate has no paid side effects
- Expired refresh leases are stolen after 600s
