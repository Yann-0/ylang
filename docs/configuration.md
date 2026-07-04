# Configuration

Ylang loads configuration from **environment variables** at startup via `Settings.load()` in `src/ylang/settings.py`. Copy [.env.example](../.env.example) as a starting point.

## Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `YLANG_STORAGE_PATH` | `~/.ylang/ylang.db` | Path to the SQLite database file |

All templates, usage rows, and facts are stored in this single file. Ylang does not upload data to any Ylang-operated cloud service.

## MCP transport

| Variable | Default | Description |
|----------|---------|-------------|
| `YLANG_TRANSPORT` | `stdio` | `stdio` (subprocess) or `http` (streamable HTTP) |
| `YLANG_HOST` | `0.0.0.0` | Bind address when transport is `http` |
| `YLANG_PORT` | `8787` | Bind port when transport is `http` |
| `YLANG_AUTH_TOKEN` | *(none)* | **Required** for `http` transport. Bearer token for MCP clients |

### stdio (default)

Used by Cursor and other MCP clients that spawn a subprocess:

```json
{
  "mcpServers": {
    "ylang": {
      "command": "python",
      "args": ["-m", "ylang"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-..."
      }
    }
  }
}
```

### HTTP (remote / shared instance)

```bash
export YLANG_TRANSPORT=http
export YLANG_PORT=8787
export YLANG_AUTH_TOKEN="$(openssl rand -hex 32)"
export YLANG_STORAGE_PATH=/srv/ylang/data/ylang.db
python -m ylang
```

Client config:

```json
{
  "mcpServers": {
    "ylang": {
      "url": "http://127.0.0.1:8787/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

## LLM provider API keys

Ylang routes LLM calls through [LiteLLM](https://github.com/BerriAI/litellm). Cloud models are skipped when their provider key is missing.

| Variable | Provider | Example models |
|----------|----------|----------------|
| `OPENAI_API_KEY` | OpenAI | `openai/gpt-4o`, `openai/o3-mini` |
| `ANTHROPIC_API_KEY` | Anthropic | `anthropic/claude-3-5-sonnet-latest` |
| `MISTRAL_API_KEY` | Mistral | `mistral/mistral-large-latest` |
| `PERPLEXITY_API_KEY` | Perplexity | `perplexity/sonar` |

Models without a provider prefix (e.g. `ollama/qwen2.5`) do not require a cloud API key.

## Model routing

Ylang selects models by **activity** (`code`, `search`, `reason`, `improve`, `other`). Each activity has a quality-ordered candidate list.

| Variable | Activity | Default first model |
|----------|----------|---------------------|
| `YLANG_MODELS_CODE` | Code generation | `anthropic/claude-3-5-sonnet-latest` |
| `YLANG_MODELS_SEARCH` | Search / retrieval | `perplexity/sonar` |
| `YLANG_MODELS_REASON` | Reasoning | `openai/o3-mini` |
| `YLANG_MODELS_IMPROVE` | Prompt improvement | `anthropic/claude-3-5-sonnet-latest` |
| `YLANG_MODELS_OTHER` | Fallback activity | `mistral/mistral-small-latest` |

Values are comma-separated LiteLLM model strings, highest quality first:

```bash
export YLANG_MODELS_IMPROVE="anthropic/claude-3-5-sonnet-latest,openai/gpt-4o,mistral/mistral-small-latest"
```

### Legacy single-model overrides (deprecated)

| Variable | Replacement |
|----------|---------------|
| `YLANG_MODEL_CODE` | `YLANG_MODELS_CODE` |
| `YLANG_MODEL_SEARCH` | `YLANG_MODELS_SEARCH` |
| `YLANG_MODEL_REASON` | `YLANG_MODELS_REASON` |
| `YLANG_MODEL_OTHER` | `YLANG_MODELS_OTHER` |

### Routing behavior

| Variable | Default | Description |
|----------|---------|-------------|
| `YLANG_FALLBACK_MODEL` | `ollama/qwen2.5` | Local floor model when cloud routes fail |
| `YLANG_QUALITY_BAND` | `0` | Rank offset for cost tie-break within quality band |
| `YLANG_PROVIDER_COOLDOWN_SECONDS` | `60` | Skip provider after retryable failure (429, 5xx) |
| `YLANG_DAILY_BUDGET_USD` | *(none)* | Optional rolling 24h spend cap; over-budget models skipped |

On startup, the server prints configured providers and per-activity routing to stderr.

### Cursor model slug aliases

When `improve_prompt` receives a Cursor IDE model slug (e.g. `claude-sonnet-4-5`), the model router maps it to a LiteLLM provider string. See `src/ylang/core/model_router.py` for the alias table.

## Cursor hook overrides

| Variable | Description |
|----------|-------------|
| `YLANG_HOOK_DISABLED` | Set to `1` to skip auto prompt improvement |
| `YLANG_HOOK_MODEL` | Model slug passed to `improve_prompt` (default `claude-sonnet-4-5`) |
| `YLANG_MCP_URL` | Override MCP HTTP URL for hooks (default: read from `~/.cursor/mcp.json`) |
| `YLANG_AUTH_TOKEN` | Bearer token for hook MCP calls (also read from mcp.json) |

## Local Ollama fallback

To use a local model when cloud providers are unavailable:

1. Install and run [Ollama](https://ollama.com).
2. Pull a model: `ollama pull qwen2.5`
3. Set fallback (optional): `export YLANG_FALLBACK_MODEL=ollama/qwen2.5`

LiteLLM talks to Ollama at `http://localhost:11434` by default.

## Configuration object

Programmatic access:

```python
from ylang.settings import Settings

settings = Settings.load()
print(settings.resolved_storage_path())
print(settings.activity_model_lists)
```

See [architecture.md](architecture.md) for how settings flow into `Engine` and `ModelRouter`.
