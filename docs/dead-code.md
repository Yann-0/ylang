# Dead code and stub audit

Audit of `src/ylang/` for unused exports, stub seams, and wiring gaps. **Nothing listed here should be deleted without an explicit decision** — this document flags items only.

Last updated: 2026-07-04 (full doc sync with gateway face).

Method: read modules under `src/ylang/`, grep for imports and call sites across the repo.

---

## OpenAI gateway (live)

| Symbol | File | Status |
|--------|------|--------|
| `register_gateway_routes` | `gateway/routes.py` | Wired on HTTP transport in `mcp/server.py` |
| `resolve_gateway_model` | `gateway/mapping.py` | Maps `route-*` and passthrough models |
| `Engine.complete_stream` | `core/engine.py` | Used for SSE streaming |

See [gateway.md](gateway.md).

---

## Pattern detection (wired in Phase 1)

`UsagePatternDetector` is registered at MCP startup (`mcp/server.py`). MCP tools `detect_patterns` and `save_learned_template` are live.

| Symbol | Status |
|--------|--------|
| `register_pattern_detector` | Called in `mcp/server.py` and test fixtures |
| `UsagePatternDetector.detect` | Used by `detect_patterns` tool |
| `propose_template_from_pattern` | Used by `detect_patterns` tool |
| `Library.save(..., source="learned")` | Used by `save_learned_template` |

`PatternDetector` ABC remains the extension point for alternate detectors.

---

## Improver registry exports (partially unused)

| Symbol | Status |
|--------|--------|
| `default_auto_apply` | **Used** by `improver.py`. Returns `false` for precision tools and `plan`/`debug` modes; `true` for other tools/modes. |
| `is_precision_tool` | **Used internally** by `default_auto_apply`; not called elsewhere. |
| `PRECISION_TOOLS` | Exported; **never referenced** outside `registry.py`. |
| `ChangeKind` | Exported; **never imported** externally. |

Precision-tool classification is defined for future auto-apply policy but not consumed yet.

---

## Core package re-exports (unused externally)

`Engine` is wired: `mcp/server.py` → `improver/improver.py` → `Engine.complete()`.

These symbols are exported via `core/__init__.py` but have **no imports outside `core/`**:

| Symbol | Status |
|--------|--------|
| `DEFAULT_ACTIVITY_MODELS` | Used only inside `Engine` / router init |
| `FALLBACK_MODEL` | Default in `Engine.__init__` |
| `Activity`, `Message`, `CompletionResult` | Referenced inside `engine.py` and tests |

---

## Usage schema fields (written, partially consumed)

| Item | Status |
|------|--------|
| `improver_accepted=True` | Set when validation passes and text changed, via MCP `accepted` / `record_acceptance_only`, or the Cursor hook. |
| `CompletionResult.error` | Set in engine; improver reads only `.success` and `.content`. |

---

## MCP layer and deps

| Item | Status |
|------|--------|
| `YlangDeps.surface` | Field set to `"mcp"`; **never read** by tool handlers. |

---

## Package-level unused exports

| Symbol | Status |
|--------|--------|
| `__version__` | Public via `ylang.__version__`; not in all `__all__` re-exports. |
| `SeedTemplateSpec`, `SEED_TEMPLATES` | Module-private; used by `ensure_seeds()`. |
| `ylang.mcp` package re-exports | Callers import from submodules directly. |
| `usage` re-exports | Callers import from `ylang.usage.store` directly. |

---

## `importer/` (CLI + MCP, not dead)

- MCP tool: `import_public_prompts`
- CLI: `python -m ylang.importer`
- Tested in importer tests

---

## Summary

- **0 stub faces** — gateway is live on HTTP transport.
- **Several exported symbols** never called (`is_precision_tool`, `PRECISION_TOOLS`, some core re-exports).
- **1 deps field** never read (`YlangDeps.surface`).
- **2 usage-schema fields** reserved for improver-acceptance / error surfacing.

No deletions recommended in Phase 1; implement or wire when the corresponding feature lands.
