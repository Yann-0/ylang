# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
