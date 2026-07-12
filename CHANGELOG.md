# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-07-11

### Added

- **MCP server** (stdio and HTTP transports) with **11 tools**:
  `improve_prompt`, `save_template`, `recall_template`, `list_templates`,
  `import_public_prompts`, `remember`, `recall_facts`, `recall_usage`,
  `usage_summary`, `detect_patterns`, and `save_learned_template`
- **Quality-first model routing** across four cloud providers (OpenAI, Anthropic,
  Mistral, Perplexity) with activity-based selection, provider cooldown, usage-based
  preference boost, optional daily budget cap, and an **Ollama floor**
  (`ollama/qwen2.5` fallback)
- **OpenAI-compatible HTTP gateway** on the same process as MCP when
  `YLANG_TRANSPORT=http`: `POST /v1/chat/completions`, `GET /v1/models`,
  `GET /usage`, and `GET /health`; virtual route models (`route-code`,
  `route-search`, `route-reason`, `route-other`) for activity-based chat routing
- **HTTP transport with bearer auth** — `YLANG_AUTH_TOKEN` required on `/mcp`,
  `/v1/*`, and `/usage`; `GET /health` is unauthenticated
- **Local template library** — versioned prompts with public CSV import
  (`import_public_prompts`) and learned-template proposals from usage patterns
- **Scoped memory** — user facts via `remember` / `recall_facts`, injected into
  improver context
- **Usage tracking** — every LLM call logged to SQLite with cost, latency, and
  activity; aggregates via `recall_usage` / `usage_summary` and the `GET /usage`
  Chart.js dashboard

[Unreleased]: https://github.com/Yann-0/ylang/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Yann-0/ylang/releases/tag/v0.1.0
