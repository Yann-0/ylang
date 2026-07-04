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

## Phase 1 scope

Ylang Phase 1 includes:

- MCP server (stdio and HTTP transports)
- Propose-only prompt improver with Cursor mode awareness
- Local versioned template library with public prompt import
- Usage logging and aggregation
- Scoped user facts (remember / recall)
- Pattern detection for learned templates

Not in Phase 1: optimizer, provenance, GitHub/KB sources, hosted team features, desktop gateway (stub only).
