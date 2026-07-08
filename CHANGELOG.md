# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.0] - 2026-07-08

### Added

- Prompt Usage Analytics & Optimization module (PAO-001–014)
- Persist improver outcome metadata on usage rows (`improver_validated`, `improver_changed`, rejection reason, task class, cursor mode)
- MCP `improver_analytics`, `template_effectiveness_report`, `optimization_suggestions`, `record_prompt_edit`
- CLI `ylang usage improver-report`; digest includes optimization suggestions
- Dashboard improver panels (accept rate by mode, top rejection reasons)
- Outcome-aware template retrieval (`YLANG_RETRIEVAL_EFFECTIVENESS_WEIGHT`)
- Semantic pattern detection (`YLANG_PATTERN_DETECTOR=semantic`)
- Dynamic prompt block assembly via `block:*` template tags
- Mode-aware optimization layer (`improver/mode_optimizer.py`)
- Prompt A/B experiments table and assignment (`YLANG_EXPERIMENTS=1`)
- Optional self-critique improver pass (`YLANG_IMPROVER_CRITIQUE=1`)
- Edit feedback capture in Cursor hook (`YLANG_CAPTURE_EDIT_FEEDBACK=1`)
- SQLite migrations: usage outcome columns, `feedback_events`, `prompt_experiments`

### Changed

- Version 0.4.0; MCP tool count 16
- `recall_usage` exposes full improver context and outcome fields

## [0.3.0] - 2026-07-05

### Added

- GitHub Actions CI (pytest + ruff; pyright non-blocking)
- Schema migrations (`schema_migrations`, facts workspace, usage context templates, FTS5)
- `GET /health` (unauthenticated; bearer-exempt)
- Optional HTTP rate limiting via `YLANG_RATE_LIMIT_PER_MINUTE`
- Configurable Cursor model aliases (`deploy/ylang.models.json`, `YLANG_MODEL_ALIASES_PATH`)
- CLI: `ylang backup`, `ylang export`, `ylang import`, `ylang doctor`
- MCP `search_templates` (FTS5)
- Workspace-scoped facts (`remember` / `recall_facts` `workspace` param)
- Improver analysis task detection; relaxed validation for plan/analysis prompts
- Usage digest includes `ylang patterns apply` hints
- JSON logging via `YLANG_LOG_FORMAT=json`
- Startup warning when HTTP gateway + hooks may double LLM calls
- Template recall tracking on usage rows (`improver_context_templates`)

### Changed

- Version 0.3.0; MCP tool count 12

## [Unreleased previous]

### Added

- GitHub Release workflow notes for v0.2.0; nightly Ollama `@pytest.mark.llm_e2e` CI (`.github/workflows/llm-e2e.yml`)
- CLI `ylang patterns apply` — interactive or `--index` / `--yes` to save learned templates
- CLI `ylang usage digest --last-days 7` — text digest with top patterns and budget warning
- Learned templates auto-surfaced in improver context (`YLANG_LEARNED_TEMPLATE_LIMIT`, default 2)
- Preference routing uses `improver_accepted` counts for improver buckets (`improve`, `code`, `reason`)
- Gateway load test script `scripts/gateway_load_test.py`
- Deploy docs and scripts: `setup-cli-access.sh`, `ylang-cli` wrapper, shared `ylang` group permissions for systemd SQLite CLI

### Changed

- Operational tuning docs: hooks vs gateway, `YLANG_MODELS_IMPROVE`, `YLANG_DAILY_BUDGET_USD` recipes
- Architecture notes on concurrent gateway profiling (thread offload sufficient at current scale)

## [0.2.0] - 2026-07-04

### Added

- Streaming gateway tool-call passthrough: `tools` / `tool_choice` forwarded in SSE; `tool_calls` deltas emitted
- Streaming usage token counts in gateway SSE (final chunk with `usage` when LiteLLM provides it)
- Rich usage dashboard with Chart.js charts (cost over time, activity/model breakdown, daily success rate); auto-refresh on `GET /usage`
- CLI `ylang patterns suggest` — pretty-print learned template proposals from `UsagePatternDetector`
- Optional `@pytest.mark.llm_e2e` smoke test against reachable Ollama
- In-memory template list cache in `Library.list()` with invalidation on save
- `daily_usage_buckets()` for per-day cost/request aggregation
- Pattern detection v2, CLI usage analytics, gateway tool calling (non-streaming), budget warnings, async SQLite (Phases 1–3)

### Changed

- Gateway streaming forwards `tools` / `tool_choice` to LiteLLM (parity with non-streaming)
- Usage dashboard upgraded from static bars to live Chart.js charts

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

[Unreleased]: https://github.com/Yann-0/ylang/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Yann-0/ylang/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Yann-0/ylang/releases/tag/v0.1.0
