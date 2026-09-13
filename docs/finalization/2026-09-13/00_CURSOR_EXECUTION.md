# 00 — Cursor execution

## Safety

- Work on current HEAD. Do not reset to a historical review SHA.
- Preserve uncommitted user files. Do not force-push. Do not publish or
  expose Ylang publicly.
- Do not rebuild the library, gateway, importer platform, or experiment
  store. Extend them.
- Default CI stays deterministic and offline.
- No production-traffic experiments, private-history replay, automatic
  promotion, policy auto-apply, or implementation push without authorization.

## Sequence

1. Record HEAD and `git status`. Read `.cursor/rules`.
2. Reproduce `ruff check .`, `pyright`, `pytest -m "not llm_e2e and not network"`,
   `mkdocs build --strict`.
3. Recheck live GitHub layouts. Disable incompatible sources honestly.
4. Fail closed: license, truncated trees, partial downloads, last-known-good,
   serialized refresh, intervals.
5. Bounded Engine evaluation with inspect remaining the default.
6. Versioned attribution with unknown unversioned events.
7. CLI/Portal: expose distinctions; inspect must not become paid.
8. Update docs listed in [03](03_DOCUMENTATION_RELEASE_GATES.md).
9. Run quality gates plus acceptance scenarios.
10. Report LIBRARY_READY / LIVE_SOURCE_VERIFIED / EVALUATION_EXECUTION_VERIFIED /
    QUALITY_IMPROVEMENT_DEMONSTRATED separately.

## Commands

```bash
ruff check .
pyright
pytest -m "not llm_e2e and not network"
mkdocs build --strict
YLANG_NETWORK_TESTS=1 pytest -m network   # optional, live contracts
```

Paid execute is never part of default CI.
