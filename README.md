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

One shared **core engine** (`Engine` + `ModelRouter` + LiteLLM) backs thin **faces**. Phase 1 ships the MCP adapter; a desktop gateway is stubbed for later. Business logic never lives in MCP tool handlers — they only serialize inputs and outputs.

```
src/ylang/
├── core/       # Engine, routing, SQLite, memory
├── improver/   # Propose-only prompt improvement
├── library/    # Versioned templates + pattern detection
├── usage/      # Usage store and aggregates
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

## Phase 1 scope

Improver (propose-only), MCP server, local library, usage logging, facts, pattern detection. No optimizer, provenance, GitHub/KB sources, or hosted team features in this phase.
