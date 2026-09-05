# Models and routing

Ylang selects LiteLLM models with **quality-first activity lists**, Cursor slug aliases, provider key gates, and a local Ollama fallback floor. Defaults target **August 2026** frontier models.

Canonical code: `src/ylang/settings.py` (`DEFAULT_ACTIVITY_MODEL_LISTS`), `src/ylang/core/model_aliases.py`, `src/ylang/core/model_router.py`.

## Default activity lists

When no `YLANG_MODELS_*` env override and no console runtime override is set:

| Activity | Default order (left = highest priority) |
|----------|-----------------------------------------|
| `code` | `anthropic/claude-opus-5` → `openai/gpt-5.5` → `anthropic/claude-sonnet-5` → `mistral/mistral-medium-latest` |
| `reason` | `anthropic/claude-fable-5` → `anthropic/claude-opus-5` → `openai/gpt-5.5` → `anthropic/claude-sonnet-5` |
| `search` | `perplexity/sonar-pro` → `perplexity/sonar-reasoning-pro` → `anthropic/claude-sonnet-5` → `gemini/gemini-3.7-flash` |
| `improve` | `anthropic/claude-sonnet-5` → `openai/gpt-5.5` → `mistral/mistral-medium-latest` → `mistral/mistral-small-latest` |
| `other` | `anthropic/claude-sonnet-5` → `openai/gpt-5.5` → `gemini/gemini-3.7-flash` → `mistral/mistral-small-latest` |

**Fallback floor:** `ollama/qwen2.5` (`YLANG_FALLBACK_MODEL`).

Candidates whose provider key is missing are `skipped:no_key` and never selected.

## Provider keys

| Env var | Provider | LiteLLM prefix | Example models |
|---------|----------|----------------|----------------|
| `OPENAI_API_KEY` | OpenAI | `openai/` | `openai/gpt-5.5`, `openai/gpt-5.5-pro` |
| `ANTHROPIC_API_KEY` | Anthropic | `anthropic/` | `anthropic/claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `MISTRAL_API_KEY` | Mistral | `mistral/` | `mistral/mistral-medium-latest`, `mistral-small-latest`, `mistral-large-latest` |
| `PERPLEXITY_API_KEY` | Perplexity | `perplexity/` | `perplexity/sonar-pro`, `sonar-reasoning-pro` |
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | Google Gemini | `gemini/` / `google/` | `gemini/gemini-3.7-flash`, `gemini/gemini-3.1-pro-preview` |

## Cursor slug aliases

| Cursor slug | LiteLLM target |
|-------------|----------------|
| `claude-4.6-*sonnet*`, `claude-sonnet-4-*`, `composer`, `composer-2.5-fast` | `anthropic/claude-sonnet-5` |
| `claude-4.6-opus-*`, `claude-opus-4-*` | `anthropic/claude-opus-5` |
| `gpt-5.5-medium` | `openai/gpt-5.5` |
| `gpt-5.3-codex-high-fast` | `openai/gpt-5.5` (Codex is Responses-API only; chat/gateway uses GPT-5.5) |
| `gemini-3.1-pro` | `gemini/gemini-3.7-flash` (current GA workhorse) |
| `gpt-4o-mini`, `ollama/gpt-4o-mini`, `ylang-mini` | `ollama/qwen-coder-14b` (local; avoids LiteLLM OpenAI collision) |

Prefix rules (when no exact alias): `claude-sonnet-4|5-*` → Sonnet 5, `claude-opus-4|5-*` → Opus 5, `claude-fable-*` → Fable 5.

Override the table with JSON at `YLANG_MODEL_ALIASES_PATH` or edit `deploy/ylang.models.json`.

## Console presets

Parameters page chips / Fast|Quality buttons:

- **fast** — `mistral/mistral-small-latest,anthropic/claude-haiku-4-5`
- **quality** — `anthropic/claude-sonnet-5,openai/gpt-5.5` (improve full quality preset adds Medium/Small Mistral)

## Env vs runtime overrides

Priority for each activity list:

1. Console **runtime** SQLite override (`models_code`, `models_improve`, …) when set
2. Else `YLANG_MODELS_*` env
3. Else built-in `DEFAULT_ACTIVITY_MODEL_LISTS`

If you upgraded from older defaults but still see Claude 3.5 / GPT-4o:

1. Clear `YLANG_MODELS_*` from your env file / systemd unit and restart
2. In console **Parameters**, clear the activity model fields (or reset overrides) so built-ins apply

Do not commit real keys or host-local `ylang.env`.

## Perplexity Sonar sunset

Sonar Chat Completions remains supported until **2026-09-27**, then Perplexity expects the Agent API (presets). Ylang keeps `perplexity/sonar-pro` in defaults for now; migrate later when LiteLLM/Agent wiring is ready. See [Perplexity migration guide](https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview).

## Selection pipeline

1. Resolve activity (`code` / `search` / `reason` / `improve` / `other`)
2. Load candidate list (defaults ← env ← runtime)
3. Preference reorder from recent usage success (skipped for `improve`)
4. Daily budget filter (drop cloud when over `YLANG_DAILY_BUDGET_USD`)
5. Availability (API key + provider cooldown)
6. Quality-band cost tie-break via LiteLLM model info
7. Attempt chain: optional explicit model → selected → remaining available → fallback floor

Full env reference: [configuration.md](configuration.md). Gateway passthrough: [gateway.md](gateway.md).
