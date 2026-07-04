# Ylang — Backlog shipped

**Date:** 2026-06-30 (updated 2026-07-04)  
**Status:** All Phase 2 + 3 backlog items shipped

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

### Phase 2 (original)

- [x] Pattern detection MVP (`UsagePatternDetector` + `detect_patterns` tool)
- [x] Learned template source (`save_learned_template` MCP tool)
- [x] Budget meter (2B) — `YLANG_DAILY_BUDGET_USD` + `apply_budget_filter`
- [x] Preference ordering (2C) — success-based model boost from usage
- [x] Precision-tool auto-apply policy — non-precision tools get `auto_apply_default=True` hint
- [x] Usage analytics — `usage_summary` MCP tool
- [x] `import_public_prompts` MCP tool — public CSV import wired
- [x] OpenAI-compatible gateway — `POST /v1/chat/completions`, `GET /v1/models`, streaming SSE
- [x] Usage activity normalization at write time (`improve:Cursor` → `improve:agent`)

### Phase 1 (2026-07-04)

- [x] Usage aggregate cache — 45s TTL on `summarize_usage` / `rolling_cost` row recall
- [x] Gateway completion token parity — non-streaming `usage.completion_tokens` + `total_tokens`
- [x] `improver_accepted` wiring — MCP `accepted` / `record_acceptance_only`; Cursor hook records acceptance

### Phase 2 (2026-07-04)

- [x] Pattern detection v2 — `improver_input_sample` column; cluster by normalized prompt text similarity
- [x] CLI usage report — `ylang usage summary --last-days 7` / `--last-hours N`
- [x] Budget meter hardening — edge-case integration tests; 80% startup stderr warning

### Phase 3 (2026-07-04)

- [x] Local usage dashboard — `GET /usage` on HTTP transport + `ylang usage dashboard`
- [x] Gateway tool calling passthrough — `tools` / `tool_choice` forwarded; `tool_calls` in response
- [x] Async SQLite — sync store ops run via `anyio.to_thread.run_sync` in gateway handlers

## Remaining (future)

- Rich usage analytics UI with live charts (beyond static HTML)
- Streaming tool-call passthrough
- Full aiosqlite migration (only if profiling shows thread offload insufficient)
