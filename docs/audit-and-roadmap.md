# Ylang — Deep-Dive Audit & Roadmap

> **Historical document (2026-06-30).** This audit predates the live OpenAI gateway, 11 MCP tools, consolidated SQLite connection, expanded test suite, and **Phase 4 (v0.2.0)** shipping. For current status see [README.md](../README.md#status), [backlog-shipped.md](backlog-shipped.md), and [architecture.md](architecture.md).

## Phase 4 status (2026-07-04)

All Phase 4 backlog items shipped in v0.2.0 — see [backlog-shipped.md](backlog-shipped.md#phase-4-2026-07-04--v020). This section supersedes remaining gaps listed below for gateway streaming, dashboard, and pattern CLI.

**Date:** 2026-06-30  
**Scope:** Phase 1 codebase at `src/ylang/`  
**Status:** 26 tests passing; 6 MCP tools live; local-first SQLite storage

---

## Executive summary

Ylang Phase 1 delivers a well-layered MCP server: thin adapter (`mcp/`), shared core (`core/`), and feature modules (`improver/`, `library/`, `usage/`, `importer/`). Business logic is not duplicated in the MCP layer — a design goal that is consistently met.

**Strengths:** clear module boundaries, propose-only improver with post-LLM validation guardrails, usage logging from day one, idempotent seed templates, quality-first model router with cost tie-break.

**Largest functional gap:** memory **write** is wired (`remember`) but **read** is not (`MemoryStore.recall` has no MCP tool).

**Largest quality gap:** test coverage is strong on MCP integration happy paths but weak on engine, model router, and improver validation — the paths that determine reliability and safety.

---

## Architecture

```
python -m ylang
  └── mcp/server.py:run_server()
        ├── UsageStore      (usage/store.py)
        ├── Library         (library/store.py + seeds)
        ├── MemoryStore     (core/memory.py)
        ├── Engine          (core/engine.py + model_router.py)
        ├── Improver        (improver/improver.py)
        └── YlangDeps → register_tools (mcp/tools.py)
```

All three stores share one SQLite file (`~/.ylang/ylang.db`, override via `YLANG_STORAGE_PATH`) as **separate connections**. Library and usage use WAL + busy_timeout; memory does not (minor inconsistency).

### Module responsibilities

| Module | Role |
|--------|------|
| `settings.py` | Pydantic config from env; provider keys; per-activity model lists |
| `core/engine.py` | LiteLLM completion, fallback chain, usage write on every call |
| `core/model_router.py` | Activity routing, cost tie-break, provider cooldown, Cursor slug aliases |
| `core/memory.py` | SQLite `facts` table; remember/recall API |
| `improver/` | Propose-only structural prompt improvement + validation |
| `library/` | Versioned templates, 3 seed templates, patterns stub (Phase 2+) |
| `usage/` | Raw usage rows; time-window recall via MCP |
| `mcp/` | FastMCP adapter, 6 tools, optional HTTP + bearer auth |
| `importer/` | CLI to import external CSV prompts as seeds (not in MCP surface) |

### MCP tool → backend map

| Tool | Backend | Phase 1 status |
|------|---------|----------------|
| `improve_prompt` | `Improver` → `Engine` | Complete |
| `save_template` | `Library.save` | Complete |
| `recall_template` | `Library.recall` + render | Complete |
| `list_templates` | `Library.list` | Complete |
| `remember` | `MemoryStore.remember` | Complete |
| `recall_usage` | `UsageStore.recall_usage` | Complete |
| *(missing)* `recall` | `MemoryStore.recall` | **Not exposed** |

---

## Test coverage

**26 tests** across 3 modules (all passing):

| File | Tests | What it covers |
|------|-------|----------------|
| `tests/integration/test_mcp_tools.py` | 14 | All 6 MCP tools E2E; mocked improver LLM; usage side-effects |
| `tests/test_importer.py` | 9 | CSV import, slugify, idempotency |
| `tests/test_improver_parse.py` | 3 | JSON extraction and parse helpers only |

### Untested (high-risk) paths

- `Engine.complete()` — fallback chain, retryable errors, cooldown
- `ModelRouter` — model selection, Cursor slug aliases, env overrides
- `Improver._validate()` — safety rules (numbers, modals, replay consistency)
- `MemoryStore.recall()` — entire read path
- Improver LLM failure → safe fallback
- HTTP transport + bearer auth middleware
- Template v2+ versioning, missing render params
- `settings.py` env parsing edge cases

See also [dead-code.md](./dead-code.md) for stub/unwired symbol inventory.

---

## Feature completeness vs Phase 1 vision

Phase 1 guardrails (from `.cursor/rules/00-project.mdc`):

- ONE core engine; faces are thin adapters — **met**
- Improver propose-only; auto-apply off — **met**
- Local-first storage — **met**
- Usage store written from day one — **met**
- No optimizer, provenance, GitHub/KB, hosted/team — **met** (stubs only)

### Beyond the checklist

| Capability | Status |
|------------|--------|
| HTTP transport + bearer auth | Implemented, untested |
| Multi-version templates | Implemented, lightly tested |
| Cursor model slug aliases | Implemented in router |
| Importer CLI | Complete, tested, outside MCP |

---

## Known gaps & Phase 2 seams

Documented in code and [dead-code.md](./dead-code.md):

| Seam | Location | Phase | Purpose |
|------|----------|-------|---------|
| `library/patterns.py` | Full stub module | 2+ | Detect usage patterns → propose templates |
| `source="learned"` | `library/store.py` | 2+ | Auto-generated templates from patterns |
| `apply_budget_filter` | `model_router.py:94` | 2B | Rolling spend cap from UsageStore |
| `apply_preference_order` | `model_router.py:84` | 2C | Boost models user accepts often |
| `is_precision_tool` / `PRECISION_TOOLS` | `improver/registry.py` | 2 | Auto-apply policy per tool |
| `improver_accepted` usage field | `engine.py` | 2 | Track when user accepts improver suggestions |
| Memory recall MCP tool | — | 1.5 | Expose existing `MemoryStore.recall` |

---

## Code quality notes

**Strengths:** consistent typing, dataclasses, Pydantic settings; improver validation is thorough; graceful degradation on LLM/parse failures.

**Inconsistencies to address:**

- MCP error handling: `remember` returns `{ok: false}`; `recall_template` returns `{found: false}`; parser errors may propagate uncaught
- `library.render` missing params raise `KeyError` at MCP boundary
- `improve:{tool}` activity maps to `"other"` bucket — suboptimal model routing for improver calls
- Three SQLite connections without shared WAL on memory store

---

## Roadmap

### Near-term (Phase 1.x) — days to 2 weeks

| # | Item | Effort | Impact | Notes |
|---|------|--------|--------|-------|
| 1 | **Add `recall_facts` MCP tool** | S | High | Wire `MemoryStore.recall`; scope + limit params |
| 2 | **Unit tests: improver `_validate`** | M | High | Safety-critical; numbers, modals, replay, length ratio |
| 3 | **Unit tests: Engine + ModelRouter** | M | High | Fallback chain, cooldown, slug resolution |
| 4 | **Align memory SQLite pragmas** | S | Medium | WAL + busy_timeout like library/usage |
| 5 | **MCP error handling consistency** | S | Medium | Catch KeyError, parse errors; structured responses |
| 6 | **Dedicated `improve` activity bucket** | S | Medium | `YLANG_MODELS_IMPROVE` or map `improve:*` → reason |
| 7 | **Template versioning tests** | S | Low | Save v2, recall by version |
| 8 | **HTTP transport + auth tests** | S | Low | Bearer 401, missing token startup guard |

Effort key: **S** = ≤1 day, **M** = 2–4 days, **L** = 1+ week

### Phase 2 backlog — weeks to months

| # | Item | Effort | Depends on | Notes |
|---|------|--------|------------|-------|
| 9 | **Pattern detection stub → MVP** | L | Usage data volume | `PatternDetector.detect()`; propose-only templates |
| 10 | **Learned template source** | M | #9 | Allow `source="learned"` save path |
| 11 | **Budget meter (2B)** | M | Usage aggregations | Rolling spend helper + `apply_budget_filter` |
| 12 | **Preference ordering (2C)** | M | `improver_accepted` tracking | Wire acceptance signals from usage |
| 13 | **Precision-tool auto-apply policy** | S | #12 | Use `is_precision_tool`; still propose-only default off |
| 14 | **Consolidate SQLite connections** | M | — | Single connection manager or shared pool |
| 15 | **Desktop gateway face** | XL | Stable core API | Second adapter over same engine |
| 16 | **Usage analytics dashboard** | L | — | Local UI over recall_usage rows |

### Explicitly out of scope (Phase 1 guardrails)

- Optimizer / automatic prompt rewriting without user review
- Provenance / GitHub / KB template sources
- Hosted or team features
- Cloud storage of templates, facts, or usage

---

## Improver note: why `improve_prompt` returned no changes

The improver is **structural only** — it may fix grammar, headings, bullets, and surface missing format constraints. It **cannot** add scope, clarify vague goals, or expand requirements.

Prompts like *"do deep dive analysis… provide roadmap… ask questions"* are substantively vague, not structurally broken. The model correctly returns `changes: []`.

For analysis tasks, refine the prompt manually with: target repo, deliverable format, horizon, and explicit output sections.

---

## Context-aware improver (Phase 1 extension)

`improve_prompt` uses context by default (`use_context=true`). The improver user message always includes three sections when context is enabled:

- **Conversation** — client-supplied history (last 20 turns / 8k chars). Clients should pass `conversation: [{role, content}, ...]` for best results; when omitted, the section shows an explicit empty placeholder so the model knows no prior turns were provided.
- **Project facts** — local memory (shareable + private; 20 facts / 2k chars)
- **Reference prompts** — relevant library templates via tag/keyword scoring (3 prompts / 4k chars)

Templates now support `visibility` (`public`/`private`, default private for user/learned, public for seeds) and `tags` for retrieval. Pass `use_context=false` to opt out (backward compatible).

**Cursor mode optimization:** `improve_prompt` resolves Cursor mode (`agent`, `plan`, `debug`, `ask`, `multitask`) from optional `mode`, the `tool` name, or prompt keywords. Mode-specific guidance is injected into the LLM user message; usage logs `improve:{mode}`; model routing maps ask/plan → `reason`, agent/debug/multitask → `code`. Response includes `cursor_mode` and `mode_source`.

---

## Definition of done for this audit

- [x] Architecture mapped module-by-module
- [x] Test coverage assessed with gaps listed
- [x] Phase 1 completeness checked against guardrails
- [x] dead-code.md gaps incorporated
- [x] Near-term and Phase 2 roadmaps with effort estimates
- [x] 26/26 tests passing at time of audit
