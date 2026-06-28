# Dead code and stub audit

Audit of `src/ylang/` as of current `main`. **Nothing listed here should be deleted without an explicit decision** — this document flags unused exports, stub seams, and wiring gaps only.

Method: read all modules under `src/ylang/`, then grep for imports and call sites across the repo.

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

Related: `Library.save(..., source="learned")` is rejected at `store.py` L116–118 — reserved for the future pattern hook. `list_templates` accepts `source="learned"` as a filter (`tools.py` L174–175) but no code path creates learned templates today.

---

## Improver registry exports (partially unused)

| Symbol | File:line | Status |
|--------|-----------|--------|
| `default_auto_apply` | `registry.py` L19–22 | **Used** by `improver.py` L56. Always returns `False` (Phase 1); `tool` parameter ignored (`_ = tool`). |
| `is_precision_tool` | `registry.py` L14–16 | Exported in `improver/__init__.py` L14; **never called** anywhere in repo. |
| `PRECISION_TOOLS` | `registry.py` L5–11 | Exported in `improver/__init__.py` L12; **never referenced** outside `registry.py`. |
| `ChangeKind` | `types.py` L8 | Exported in `improver/__init__.py` L9; **never imported** externally (only used as `Change.kind` annotation). |

Precision-tool classification is defined for future auto-apply policy but not consumed yet.

---

## Core package re-exports (unused externally)

`Engine` is wired: `mcp/server.py` L53–54 instantiates it; `improver/improver.py` L57–66 calls `Engine.complete()`.

These symbols are exported via `core/__init__.py` but have **no imports outside `core/`**:

| Symbol | File:line | Status |
|--------|-----------|--------|
| `DEFAULT_ACTIVITY_MODELS` | `engine.py` L14–19 | Used only inside `Engine.__init__`. |
| `FALLBACK_MODEL` | `engine.py` L21 | Used only as `Engine.__init__` default. |
| `Activity`, `Message`, `CompletionResult` | `types.py` | Referenced only inside `engine.py`. |

---

## Memory recall (write wired, read unwired)

`MemoryStore.remember` is wired: `mcp/server.py` L52 → `YlangDeps.memory` (`deps.py` L20) → MCP `remember` (`tools.py` L73).

These recall paths are implemented but have **no call sites** (no MCP tool, no tests):

| Symbol | File:line | Status |
|--------|-----------|--------|
| `MemoryStore.recall` | `memory.py` L123–152 | Never called. |
| `Fact` | `memory.py` L60–67 | Return type of `recall` only. |
| `bind_memory` | `memory.py` L172–175 | Never called. |
| Module-level `remember()` | `memory.py` L178–183 | Never called (MCP uses `deps.memory.remember`). |
| Module-level `recall()` | `memory.py` L186–191 | Never called. |

---

## Usage schema fields (written, not yet consumed)

| Item | File:line | Status |
|------|-----------|--------|
| `improver_accepted=True` | `engine.py` L51, L85 | Never assigned `True`; improver always passes `False` (`improver.py` L65). |
| `CompletionResult.error` | `types.py` L27, set `engine.py` L76, L96 | Improver reads only `.success` and `.content` (`improver.py` L67–70). |

---

## MCP layer and deps

| Item | File:line | Status |
|------|-----------|--------|
| `YlangDeps.surface` | `deps.py` L21 | Field defaults to `"mcp"`; **never read** by tool handlers or server (`Engine` gets its own `surface="mcp"` at `server.py` L53). |

### Multiple SQLite connections (observation, not a crash bug)

`run_server()` in `mcp/server.py` L50–55 opens `UsageStore`, `Library`, and `MemoryStore` on the same `resolved_storage_path()` — three separate connections to one file. Valid for Phase 1; may need a single connection or WAL tuning later.

---

## Package-level unused exports

| Symbol | File:line | Status |
|--------|-----------|--------|
| `__version__` | `__init__.py` L3 | Not in `__all__`; not referenced elsewhere in repo. |
| `SeedTemplateSpec`, `SEED_TEMPLATES` | `seeds.py` L15–55 | Module-private; used only by `ensure_seeds()` (L60), not re-exported from `library/__init__.py`. |
| `ylang.mcp` package exports | `mcp/__init__.py` L3–6 | `YlangDeps`, `create_server`, `run_server` re-exported; callers import from submodules instead. |
| `usage` re-exports | `usage/__init__.py` L3 | `UsageRecord`, `UsageWindow`, `open_store` re-exported; callers import from `ylang.usage.store` directly. |

---

## MCP tools vs backend coverage

| Tool | Backend used | Gap |
|------|--------------|-----|
| `improve_prompt` | `deps.improver` → `Engine` | OK |
| `save_template`, `recall_template`, `list_templates` | `deps.library` | OK |
| `recall_usage` | `deps.store` | OK |
| `remember` | `deps.memory` | OK (recall not exposed) |

---

## `importer/` (CLI-only, not dead)

Separate entry point `python -m ylang.importer` (`importer/__main__.py`). Not wired into MCP or `python -m ylang`. Tested in `tests/test_importer.py`. Intentionally outside the MCP surface.

---

## Summary counts

- **1 full stub module** (`library/patterns.py`) exported but inactive.
- **Several exported symbols** never called (`is_precision_tool`, `PRECISION_TOOLS`, pattern APIs, core type re-exports).
- **1 deps field** never read (`YlangDeps.surface`).
- **Memory recall API** implemented but no read face yet.
- **2 usage-schema fields** reserved for future improver-acceptance / error surfacing.

No deletions recommended in Phase 1; implement or wire when the corresponding feature lands.
