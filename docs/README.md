# Ylang documentation

Ylang is a **local-first personal AI efficiency layer**: an [MCP](https://modelcontextprotocol.io) server plus an OpenAI-compatible HTTP gateway that improves prompts, manages a template library, tracks LLM usage, and remembers user facts — all backed by a single SQLite database.

## Quick links

| Document | Description |
|----------|-------------|
| [Installation](installation.md) | Virtualenv, editable install, first run |
| [Configuration](configuration.md) | Environment variables, **model prioritization**, routing, API keys |
| [Models](models.md) | Default activity lists, Cursor aliases, Gemini/OpenAI/Anthropic IDs |
| [Architecture](architecture.md) | Module layout, data flow, design principles |
| [MCP tools reference](mcp-tools.md) | Every tool: parameters, responses, examples |
| [CLI](cli.md) | `ylang` subcommands: usage, patterns, backup, export, import, doctor, purge-traces, init |
| [Cursor integration](cursor-integration.md) | Hooks, rules, auto prompt improvement, per-message `ylang-off` bypass |
| [Console](console.md) | **Full admin UI** — Overview, **Operator Hub** (`/console/control`), **Parameters** (`/console/settings`), workflows, APIs |
| [Gateway](gateway.md) | OpenAI-compatible HTTP face: `/v1/chat/completions`, `/v1/models`, `/console`, `/health`; virtual `route-*` models; bearer auth; Cursor custom-endpoint setup |
| [Deployment](deployment.md) | HTTP transport, systemd, production setup |
| [Development](development.md) | Tests, linting, scripts, project layout |
| [Database schema](database-schema.md) | SQLite tables and relationships |
| [Quality charter](quality-charter.md) | Soft limits, principles, config authority |
| [Quality loop](quality-loop.md) | Before/after metrics per improvement wave |
| [Control plane evolution](control-plane-evolution/README.md) | Local-first AI Control Plane program (Y0–Y6, gates, run log) |

## Internal / historical

| Document | Description |
|----------|-------------|
| [CHANGELOG](https://github.com/Yann-0/ylang/blob/main/CHANGELOG.md) | Version history |
| [Dead code audit](dead-code.md) | Unused exports and stub seams (**historical** audit; see architecture for current) |
| [Audit and roadmap](audit-and-roadmap.md) | **Historical** snapshot (2026-06-30) — superseded by current code |
| [Open backlog](backlog.md) | Active backlog items (not yet shipped) |
| [Backlog shipped](backlog-shipped.md) | Completed backlog items |

## Status

### Shipped

- MCP server (stdio and HTTP `/mcp`)
- OpenAI-compatible gateway on HTTP transport — `POST /v1/chat/completions`, `GET /v1/models`, `GET /console`, `GET /health`
- **Full admin console** at `/console/login` — browser auth, CRUD, template studio (params + AI improve), data browser, AI advisor, import/export/restore
- Virtual route models: `route-code`, `route-search`, `route-reason`, `route-other`
- Bearer auth on `/mcp`, `/v1/*`, and `/usage`; session cookie for console; `GET /health` unauthenticated
- Activity-based routing, fallback chain, provider cooldown, usage-based preference boost
- **Daily budget cap enforced at runtime** when `YLANG_DAILY_BUDGET_USD` is set
- Propose-only improver, template library, usage logging, facts, pattern detect/suggest/apply
- Experiment framework with console outcomes view

### Planned

- Governed auto-apply from experiment/analytics winners (still propose-only today)
- Email (remote) digest delivery — local CLI/cron + `notify-send` shipped

Not in scope: optimizer with provenance, GitHub/KB sources, hosted team features.
