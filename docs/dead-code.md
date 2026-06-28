# Dead code and stub audit

Audit of `src/ylang/` as of Phase 1 scaffold. **Nothing listed here should be deleted without an explicit decision** — this document flags unused exports, stub seams, and wiring gaps only.

Method: read all modules under `src/ylang/`, then grep for imports and call sites across the repo.

---

## Missing module: `ylang.core.memory`

| Location | Notes |
|----------|-------|
| `src/ylang/mcp/tools.py` L70–83, L218–223 | `remember` MCP tool dynamically imports `ylang.core.memory` and calls `remember(fact, scope)`. `ModuleNotFoundError` → returns `{ok: false, error: "remember is unavailable until ylang.core.memory is implemented"}`. |
| *(missing)* `src/ylang/core/memory.py` | No file exists. Facts are not persisted anywhere today. |

The tool is registered and callable but always fails until `core.memory` is implemented and wired (likely through `YlangDeps`, not ad-hoc import).

---

## Stub seam: `library/patterns.py` (Phase 2+)

Entire module is a documented stub; nothing in the running MCP path invokes it.

| Symbol | File:line | Status |
|--------|-----------|--------|
| `DetectedPattern` | `patterns.py` L10–16 | Dataclass only; no detector produces instances. |
| `TemplateProposal` | `patterns.py` L19–27 | Dataclass only; never returned. |
| `PatternDetector` | `patterns.py` L40–44 | ABC; `detect()` raises `NotImplementedError`. |
| `register_pattern_detector` | `patterns.py` L50–53 | Sets module-global `_PATTERN_DETECTOR`; never called. |
| `propose_template_from_pattern` | `patterns.py` L56–59 | Always returns `None`. |
| Re-exports | `library/__init__.py` L3–8, L13–24 | Exported in public API but unused outside `patterns.py` / `__init__.py`. |

Related: `Library.save(..., source="learned")` is rejected at `store.py` L116–118 — reserved for the future pattern hook.

---

## Unused core engine (`ylang.core`)

The shared engine is implemented but **not wired into MCP or improver**.

| Symbol | File:line | Status |
|--------|-----------|--------|
| `Engine` | `core/engine.py` L27–86 | Never instantiated outside `core/`. |
| `Engine.complete` | `core/engine.py` L43–86 | No call sites. |
| `_call_litellm`, `_parse_response` | `core/engine.py` L89–116 | Only used by `Engine`. |
| `DEFAULT_ACTIVITY_MODELS` | `core/engine.py` L14–19 | Exported via `core/__init__.py`; no external use. |
| `FALLBACK_MODEL` | `core/engine.py` L21 | Exported via `core/__init__.py`; no external use. |
| `Activity`, `Message`, `CompletionResult` | `core/types.py` | Exported via `core/__init__.py`; only referenced inside `core/engine.py`. |

**Architectural note:** `improver/improver.py` calls LiteLLM directly (`_call_litellm` L96–112) instead of delegating to `Engine`. Duplicated LiteLLM/usage-logging pattern until core is unified.

---

## Improver registry exports (partially unused)

| Symbol | File:line | Status |
|--------|-----------|--------|
| `default_auto_apply` | `registry.py` L19–22 | **Used** by `improver.py` L59. Always returns `False` (Phase 1); `tool` parameter ignored (`_ = tool`). |
| `is_precision_tool` | `registry.py` L14–16 | Exported in `improver/__init__.py` L14; **never called** anywhere in repo. |
| `PRECISION_TOOLS` | `registry.py` L5–11 | Exported in `improver/__init__.py` L12; **never referenced** outside `registry.py`. |

Precision-tool classification is defined for future auto-apply policy but not consumed yet.

---

## MCP layer: exports and deps wiring

| Item | File:line | Status |
|------|-----------|--------|
| `YlangDeps.surface` | `mcp/deps.py` L19 | Field defaults to `"mcp"`; **never read** by tool handlers or server. |
| `create_server` | `mcp/server.py` L26–30 | Exported from `mcp/__init__.py`; only called from `run_server()` L54 — not used by external callers in-repo. |
| `remember` bypasses `YlangDeps` | `mcp/tools.py` L70–83 | Uses dynamic import instead of a dependency injected at startup (inconsistent with improver/library/store). |

### Store opened before / alongside deps (observation, not a crash bug)

`run_server()` in `mcp/server.py` L47–51:

1. Opens `UsageStore` and `Library` on the same `resolved_storage_path()` (two separate SQLite connections to one file).
2. Builds `Improver(store, ...)`.
3. Builds `YlangDeps(improver, library, store)`.

Order is consistent for current tools. **Gap:** `remember` is not given `store` or a future memory backend via `YlangDeps`. Dual connections to one DB file are valid for Phase 1 but may need a single connection or WAL tuning later.

---

## Package-level unused exports

| Symbol | File:line | Status |
|--------|-----------|--------|
| `__version__` | `__init__.py` L3 | Not in `__all__`; not referenced elsewhere in repo. |
| `SeedTemplateSpec`, `SEED_TEMPLATES` | `library/seeds.py` L15–55 | Module-private usage only (`ensure_seeds` L60); not re-exported from `library/__init__.py`. |
| `_dataclass_to_dict` | `mcp/tools.py` L226–233 | Only reachable when `ylang.core.memory.remember` exists and returns a dataclass — dead path today. |

---

## MCP tools vs backend coverage

| Tool | Backend used | Gap |
|------|--------------|-----|
| `improve_prompt` | `deps.improver` | OK |
| `save_template`, `recall_template`, `list_templates` | `deps.library` | OK |
| `recall_usage` | `deps.store` | OK |
| `remember` | Dynamic `ylang.core.memory` | **Stub / missing module** |

---

## Summary counts

- **1 missing module** blocking a registered MCP tool (`core.memory`).
- **1 full stub module** (`library/patterns.py`) exported but inactive.
- **1 major unused subsystem** (`core.Engine` and related exports).
- **Several exported symbols** never called (`is_precision_tool`, `PRECISION_TOOLS`, pattern APIs).
- **1 deps field** never read (`YlangDeps.surface`).
- **1 inconsistent wiring pattern** (`remember` vs injected deps).

No deletions recommended in Phase 1; implement or wire when the corresponding feature lands.
