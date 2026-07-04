# Ylang — Backlog shipped

**Date:** 2026-06-30 (updated 2026-07-04)  
**Status:** 135 tests passing; 11 MCP tools live; OpenAI gateway on HTTP transport

See [audit-and-roadmap.md](./audit-and-roadmap.md) for the original audit (historical). This addendum records what was shipped.

## Shipped (backlog execution)

### Phase 1.x

- [x] `recall_facts` MCP tool — memory read path wired
- [x] Unit tests: improver `_validate` + LLM failure paths
- [x] Unit tests: Engine fallback + ModelRouter (cooldown, budget, preferences)
- [x] Memory SQLite pragmas aligned (shared `open_connection` with WAL)
- [x] MCP error handling consistency (`{ok, error}` on parse/render failures)
- [x] Dedicated `improve` activity bucket (`improve:*` → `improve` routing)
- [x] Template versioning integration tests
- [x] HTTP bearer auth tests
- [x] Consolidated SQLite connection via `core/stores.py`

### Phase 2

- [x] Pattern detection MVP (`UsagePatternDetector` + `detect_patterns` tool)
- [x] Learned template source (`save_learned_template` MCP tool)
- [x] Budget meter (2B) — `YLANG_DAILY_BUDGET_USD` + `apply_budget_filter`
- [x] Preference ordering (2C) — success-based model boost from usage
- [x] Precision-tool auto-apply policy — non-precision tools get `auto_apply_default=True` hint
- [x] Usage analytics — `usage_summary` MCP tool
- [x] `import_public_prompts` MCP tool — public CSV import wired
- [x] OpenAI-compatible gateway — `POST /v1/chat/completions`, `GET /v1/models`, streaming SSE
- [x] Usage activity normalization at write time (`improve:Cursor` → `improve:agent`)

## Remaining (future)

- Rich usage analytics UI (L)
- Text-based pattern clustering from improver input (today: clusters on `improve:*` activity suffix counts)
- Wire `improver_accepted` tracking from client acceptance events
