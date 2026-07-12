# Ylang documentation

Ylang is a **local-first personal AI efficiency layer**: an [MCP](https://modelcontextprotocol.io) server plus an OpenAI-compatible HTTP gateway that improves prompts, manages a template library, tracks LLM usage, and remembers user facts — all backed by a single SQLite database.

## Quick links

| Document | Description |
|----------|-------------|
| [Installation](installation.md) | Virtualenv, editable install, first run |
| [Configuration](configuration.md) | Environment variables, **model prioritization**, routing, API keys |
| [Architecture](architecture.md) | Module layout, data flow, design principles |
| [MCP tools reference](mcp-tools.md) | Every tool: parameters, responses, examples |
| [Cursor integration](cursor-integration.md) | Hooks, rules, auto prompt improvement |
| [Gateway](gateway.md) | OpenAI-compatible HTTP face: `/v1/chat/completions`, `/v1/models`, `/usage`, `/health`; virtual `route-*` models; bearer auth; Cursor custom-endpoint setup |
| [Deployment](deployment.md) | HTTP transport, systemd, production setup |
| [Development](development.md) | Tests, linting, scripts, project layout |
| [Database schema](database-schema.md) | SQLite tables and relationships |

## Internal / historical

| Document | Description |
|----------|-------------|
| [CHANGELOG](../CHANGELOG.md) | Version history |
| [Dead code audit](dead-code.md) | Unused exports and stub seams (audit only) |
| [Audit and roadmap](audit-and-roadmap.md) | **Historical** snapshot (2026-06-30) — superseded by current code |
| [Open backlog](backlog.md) | Active backlog items (not yet shipped) |
| [Backlog shipped](backlog-shipped.md) | Completed backlog items |

## Status

### Shipped

- MCP server (stdio and HTTP `/mcp`)
- OpenAI-compatible gateway on HTTP transport — `POST /v1/chat/completions`, `GET /v1/models`, `GET /usage`, `GET /health`
- Virtual route models: `route-code`, `route-search`, `route-reason`, `route-other`
- Bearer auth on `/mcp`, `/v1/*`, and `/usage`; `GET /health` unauthenticated
- Activity-based routing, fallback chain, provider cooldown, usage-based preference boost
- **Daily budget cap enforced at runtime** when `YLANG_DAILY_BUDGET_USD` is set (cloud models dropped from routing at cap; see [configuration.md](configuration.md#daily-budget-cap))
- Propose-only improver, template library, usage logging, facts, pattern detect/suggest/apply

### Planned

- Auto-evaluation loop — outcome-driven optimizations remain propose-only; no automatic apply from experiment or analytics results
- Pattern-learning maturity — manual suggest/apply workflow exists; notifications and fuller automation not yet shipped

Not in scope: optimizer with provenance, GitHub/KB sources, hosted team features.
