# Ylang documentation

Ylang is a **local-first personal AI efficiency layer**. Phase 1 ships an [MCP](https://modelcontextprotocol.io) server that improves prompts, manages a template library, tracks LLM usage, and remembers user facts — all backed by a single SQLite database.

## Quick links

| Document | Description |
|----------|-------------|
| [Installation](installation.md) | Virtualenv, editable install, first run |
| [Configuration](configuration.md) | Environment variables, **model prioritization**, routing, API keys |
| [Architecture](architecture.md) | Module layout, data flow, design principles |
| [MCP tools reference](mcp-tools.md) | Every tool: parameters, responses, examples |
| [Cursor integration](cursor-integration.md) | Hooks, rules, auto prompt improvement |
| [Gateway](gateway.md) | OpenAI-compatible `/v1/chat/completions` for Cursor model routing |
| [Deployment](deployment.md) | HTTP transport, systemd, production setup |
| [Development](development.md) | Tests, linting, scripts, project layout |
| [Database schema](database-schema.md) | SQLite tables and relationships |

## Internal / historical

| Document | Description |
|----------|-------------|
| [CHANGELOG](../CHANGELOG.md) | Version history |
| [Dead code audit](dead-code.md) | Unused exports and stub seams (audit only) |
| [Audit and roadmap](audit-and-roadmap.md) | Phase planning notes |
| [Backlog shipped](backlog-shipped.md) | Completed backlog items |

## Status

### Shipped

- MCP tools (stdio and HTTP transports)
- Provider routing and fallback chain
- HTTP transport + bearer auth
- OpenAI-compatible gateway (`/v1/chat/completions`, virtual `route-*` models)
- Propose-only prompt improver, template library, usage logging, facts, pattern detection

### Next

- Budget meter maturity (`YLANG_DAILY_BUDGET_USD`)
- Pattern-learning maturity (suggestions from repeated usage)

Not in scope: optimizer, provenance, GitHub/KB sources, hosted team features.
