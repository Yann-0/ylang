# Ylang

**Personal AI efficiency layer** — local-first prompt improvement, template library, usage tracking, and scoped memory, exposed as an [MCP](https://modelcontextprotocol.io) server.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What it does

- **Improves prompts** — Expands rough requests into structured specs; aware of Cursor modes (`agent`, `plan`, `debug`, `ask`, `multitask`)
- **Template library** — Versioned local prompts with public import from awesome-chatgpt-prompts lineage
- **Remembers facts** — Scoped user facts injected into improvement context
- **Tracks usage** — Every LLM call logged to SQLite with cost and latency
- **Detects patterns** — Suggests learned templates from repeated improver usage

All data stays on your machine unless you send it to an LLM provider you configure.

## Quick start

```bash
git clone https://github.com/Yann-0/ylang.git
cd ylang
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY, etc.
python -m ylang
```

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "ylang": {
      "command": "python",
      "args": ["-m", "ylang"]
    }
  }
}
```

Full instructions: **[docs/installation.md](docs/installation.md)**

## Documentation

| Guide | Description |
|-------|-------------|
| [docs/README.md](docs/README.md) | Documentation index |
| [Installation](docs/installation.md) | Setup on Linux, macOS, Windows |
| [Configuration](docs/configuration.md) | Environment variables, model prioritization, routing |
| [Architecture](docs/architecture.md) | Design, modules, data flow |
| [MCP tools](docs/mcp-tools.md) | Full API reference (11 tools) |
| [Cursor integration](docs/cursor-integration.md) | Hooks, auto prompt improvement |
| [Gateway](docs/gateway.md) | OpenAI-compatible `/v1/chat/completions` for Cursor routing |
| [Deployment](docs/deployment.md) | HTTP transport, systemd |
| [Development](docs/development.md) | Tests, linting, contributing |

## MCP tools (summary)

| Tool | Description |
|------|-------------|
| `improve_prompt` | Expand prompts into full specs; Cursor mode-aware |
| `save_template` / `recall_template` / `list_templates` | Local versioned template library |
| `import_public_prompts` | Import public CSV prompts (idempotent) |
| `remember` / `recall_facts` | Scoped user facts |
| `recall_usage` / `usage_summary` | Usage history and aggregates |
| `detect_patterns` / `save_learned_template` | Learn from repeated usage |

Details: [docs/mcp-tools.md](docs/mcp-tools.md)

## Architecture (one paragraph)

One shared **core engine** (`Engine` + `ModelRouter` + LiteLLM) backs thin **faces**: MCP (stdio/HTTP) and an **OpenAI-compatible gateway** (`POST /v1/chat/completions`, `GET /v1/models`) on the same HTTP server. Virtual models `route-code`, `route-search`, `route-reason`, and `route-other` trigger activity routing; any other model string passthroughs to a named provider. Business logic never lives in face handlers — they only parse, map, and serialize.

```
src/ylang/
├── core/       # Engine, routing, SQLite, memory
├── improver/   # Propose-only prompt improvement
├── library/    # Versioned templates + pattern detection
├── usage/      # Usage store and aggregates
├── gateway/    # OpenAI-compatible HTTP face
├── mcp/        # MCP server (stdio / HTTP)
└── settings.py # Typed configuration
```

## Privacy

- **Storage:** SQLite at `~/.ylang/ylang.db` (override with `YLANG_STORAGE_PATH`)
- **No Ylang cloud:** Templates, facts, and usage are never uploaded to a Ylang-operated service
- **LLM providers:** Traffic goes only to providers you configure (OpenAI, Anthropic, Ollama, etc.)

## Requirements

- Python 3.12+
- At least one LLM provider API key, or a local Ollama instance for fallback

Copy [.env.example](.env.example) for all configuration options. See **[docs/configuration.md](docs/configuration.md)** for model prioritization, routing, budget caps, and recipes.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/development.md](docs/development.md).

## License

[MIT](LICENSE) — Copyright (c) 2026 Yann

## Status and roadmap

| Area | Status |
|------|--------|
| MCP improver + hooks | **Live** — primary daily-use surface |
| OpenAI gateway (`/v1/chat/completions`) | **Live** on HTTP transport — route real Cursor traffic via `route-code` |
| Activity-based routing | **Validated** for improver; gateway routing awaits production traffic |
| Pattern detection (2C) | Wired; needs diverse usage data before trusting suggestions |
| Budget meter / peer sharing | Implemented; low urgency at solo volume |

Phase 1 ships: improver (propose-only), MCP server, gateway, local library, usage logging, facts, pattern detection. Not in scope: optimizer, provenance, GitHub/KB sources, hosted team features.
