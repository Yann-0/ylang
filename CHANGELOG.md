# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Pattern detection v2: `improver_input_sample` on usage rows; clusters similar improver prompts (difflib ≥ 85%, min 3 occurrences)
- CLI usage analytics: `ylang usage summary` and `ylang usage dashboard`
- HTTP usage dashboard at `GET /usage` (last 7 days, inline HTML/CSS)
- Gateway tool calling passthrough: optional `tools` / `tool_choice`; `tool_calls` in non-streaming responses
- Budget startup warning when rolling 24h spend ≥ 80% of `YLANG_DAILY_BUDGET_USD`
- Async SQLite access: gateway handlers run blocking store/engine calls via `anyio.to_thread.run_sync`

### Changed

- `detect_patterns` clusters on improver prompt text (`improver_input_sample`), not activity suffix alone
- Gateway routes offload sync SQLite/engine work to worker threads

### Added (prior unreleased)

- OpenAI-compatible gateway: `POST /v1/chat/completions`, `GET /v1/models`, SSE streaming, virtual `route-*` models ([gateway.md](docs/gateway.md))
- Usage activity normalization at write time (`improve:Cursor` → `improve:agent`, etc.)
- Expanded [configuration.md](docs/configuration.md): full env reference, model prioritization, routing flow, quality band, budget cap, usage-based reorder, configuration recipes
- Updated `.env.example` with all routing variables and comments
- Short-TTL in-memory cache for usage aggregates (`summarize_usage` / `rolling_cost`) to avoid per-request table scans
- `improve_prompt` optional `accepted` and `record_acceptance_only` params for improver acceptance tracking

### Changed

- Full documentation sync: README, docs index, architecture, MCP tools, database schema, installation, deployment, development, cursor integration, gateway parity notes
- README and docs updated for live gateway (replaces "stubbed for later" wording)
- HTTP bearer auth uses `secrets.compare_digest` for timing-safe comparison
- Improver: salvage plain-markdown model output and recover improved-only JSON when `changes[]` is missing (fixes `parse error: could not locate changes array`)
- Improver: accept restructured markdown specs when the model omits `changes[]` after successful parse
- Improver: pass through original prompt when the model replies in clarifying prose instead of JSON
- Improver: set `improver_accepted` when validation passes and text changed; Cursor hook records explicit acceptance
- Gateway non-streaming responses populate `completion_tokens` and correct `total_tokens` from LiteLLM usage metadata
- Historical banner on [audit-and-roadmap.md](docs/audit-and-roadmap.md); [backlog-shipped.md](docs/backlog-shipped.md) Phase 2 + 3 complete

## [0.1.0] - 2026

### Added

- MCP server with stdio and HTTP (streamable) transports
- `improve_prompt` with Cursor mode resolution and context-aware improvement
- Local versioned template library with public prompt CSV import
- Usage logging and aggregation (`recall_usage`, `usage_summary`)
- Scoped user facts (`remember`, `recall_facts`)
- Pattern detection and learned templates (`detect_patterns`, `save_learned_template`)
- Activity-based model routing via LiteLLM with fallback chain
- Cursor global hooks for auto prompt improvement (`deploy/cursor/`)

[Unreleased]: https://github.com/Yann-0/ylang/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Yann-0/ylang/releases/tag/v0.1.0
