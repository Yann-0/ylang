# Ylang — Backlog shipped

**Date:** 2026-06-30 (updated 2026-07-04)  
**Status:** All Phase 2 + 3 + 4 + 5 backlog items shipped (v0.2.0 + Phase 5 on main)

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

### Phase 4 (2026-07-04) — v0.2.0

- [x] Streaming tool-call passthrough — SSE `tool_calls` deltas; `tools` / `tool_choice` in streams
- [x] Streaming usage token counts — final SSE chunk with `usage` when LiteLLM provides it
- [x] Rich usage dashboard — Chart.js charts, cost over time, daily success rate, auto-refresh on `GET /usage`
- [x] CLI learning loop — `ylang patterns suggest` for template proposals
- [x] Template list cache — in-memory cache with invalidation on save
- [x] Optional LLM e2e smoke — `@pytest.mark.llm_e2e` against reachable Ollama
- [x] Docs polish — gateway parity table, hooks vs gateway recipe, audit banner, dead-code refresh

### Phase 5 (2026-07-04)

- [x] GitHub Release v0.2.0 — release notes from CHANGELOG
- [x] Operational tuning docs — hooks vs gateway, improver/budget recipes in configuration.md
- [x] Nightly Ollama e2e CI — `.github/workflows/llm-e2e.yml` (`pytest -m llm_e2e`, scheduled)
- [x] Preference routing validation — `improver_accepted` boost for improver buckets; integration tests
- [x] Concurrent gateway profiling — `scripts/gateway_load_test.py`; architecture findings documented
- [x] CLI `ylang patterns apply` — save proposals via `save_learned_template`
- [x] Learned templates in improver context — top N by recency (`YLANG_LEARNED_TEMPLATE_LIMIT`)
- [x] Weekly usage digest — `ylang usage digest --last-days 7`

### Phase 6 (2026-07-05) — v0.3.0

- [x] GitHub Actions CI (pytest + ruff; pyright non-blocking)
- [x] Schema migrations framework + FTS5 index
- [x] `GET /health` endpoint
- [x] Optional HTTP rate limiting (`YLANG_RATE_LIMIT_PER_MINUTE`)
- [x] External Cursor model aliases (`deploy/ylang.models.json`)
- [x] CLI `ylang backup`, `ylang export`, `ylang import`, `ylang doctor`
- [x] MCP `search_templates` (FTS5)
- [x] Workspace-scoped facts
- [x] Improver analysis task detection + relaxed plan validation
- [x] Usage digest pattern apply hints
- [x] JSON logging (`YLANG_LOG_FORMAT=json`)
- [x] Startup warning hooks + gateway double-LLM risk
- [x] Template recall tracking on usage rows

## Remaining (future)

Open backlog items live in [backlog.md](./backlog.md).
