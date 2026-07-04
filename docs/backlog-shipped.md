# Ylang — Deep-Dive Audit & Roadmap

**Date:** 2026-06-30  
**Status:** Backlog implemented — 54 tests passing; 10 MCP tools live

See [audit-and-roadmap.md](./audit-and-roadmap.md) for the original audit. This addendum records what was shipped.

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
- [x] OpenAI-compatible gateway — `POST /v1/chat/completions`, `GET /v1/models`, streaming SSE

## Remaining (future)

- Rich usage analytics UI (L)
- Store improver input text for text-based pattern clustering
- Wire `improver_accepted` tracking from client acceptance events
