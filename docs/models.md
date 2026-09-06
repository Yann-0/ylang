# Models and routing

Ylang routes by **semantic activity** first, then selects a concrete LiteLLM
`provider/model` from the current **tested policy defaults**. Those concrete
ids are implementation choices. They are not a promise that each entry is
always the newest vendor release, and they are not identity-equal to client
aliases.

Canonical code: `src/ylang/settings.py` (`DEFAULT_ACTIVITY_MODEL_LISTS`),
`src/ylang/core/model_aliases.py`, `src/ylang/core/model_router.py`,
`src/ylang/core/types.py` (`ModelResolution`).

## Semantic route → concrete model

Public configuration still uses the activity buckets:

| Activity (semantic route) | Typical policy intent |
|---------------------------|------------------------|
| `code` | High-quality coding work |
| `search` | Retrieval / web-grounded answers |
| `reason` | Deliberate reasoning / planning |
| `improve` | Prompt improvement (often cheaper/faster first) |
| `other` | Unclassified traffic |

Internal traces also record `semantic_route` / `resolved_route` as that same
bucket. Console Fast vs Quality chips change the **candidate list**, not the
activity name — no migration is required.

Flow:

```text
semantic intent (activity / route-*)
      ↓
routing policy (configured lists + constraints + evidence)
      ↓
candidate models
      ↓
resolved provider/model + resolution_reason
```

Replacing a vendor model is a configuration/policy change
(`YLANG_MODELS_*` or console Parameters), not a core architecture change.

## Tested default candidate order

When no `YLANG_MODELS_*` env override and no console runtime override is set,
the **current policy defaults** (tested in this repo) are:

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
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | Google Gemini | `gemini/` / `google/` | `gemini/gemini-3.7-flash` |

## Compatibility aliases

Aliases are **compatibility mappings**, not model identity:

```text
legacy or client identifier
        ↓
compatibility resolution
        ↓
supported current LiteLLM route
```

Example (also persisted on the usage trace):

```text
requested_alias = gemini-3.1-pro
resolved_route = search
selected_model = gemini/gemini-3.7-flash
resolution_reason = compatibility_alias
```

That does **not** mean Gemini 3.1 Pro is Gemini 3.7 Flash. It means Ylang
accepted the historical/client slug and routed it through the current tested
Gemini candidate.

Likewise `gpt-5.3-codex-high-fast` → `openai/gpt-5.5` is a Codex-style
compatibility slug for chat/gateway, not a claim that Codex and GPT-5.5 are
the same product.

| Client / legacy slug | Compatibility target |
|----------------------|----------------------|
| `claude-4.6-*sonnet*`, `claude-sonnet-4-*`, `composer`, `composer-2.5-fast` | `anthropic/claude-sonnet-5` |
| `claude-4.6-opus-*`, `claude-opus-4-*` | `anthropic/claude-opus-5` |
| `gpt-5.5-medium` | `openai/gpt-5.5` |
| `gpt-5.3-codex-high-fast` | `openai/gpt-5.5` (Codex is Responses-API only; chat/gateway uses the GPT policy default) |
| `gemini-3.1-pro` | `gemini/gemini-3.7-flash` (tested default, not “latest forever”) |
| `gpt-4o-mini`, `ollama/gpt-4o-mini`, `ylang-mini` | `ollama/qwen-coder-14b` (local; avoids LiteLLM OpenAI collision) |

Prefix rules (when no exact alias): `claude-sonnet-4|5-*` → Sonnet 5,
`claude-opus-4|5-*` → Opus 5, `claude-fable-*` → Fable 5.

Each mapping is tagged with `alias_source`:

| `alias_source` | Meaning |
|----------------|---------|
| `builtin` | Exact key from `DEFAULT_CURSOR_SLUG_ALIASES` (or an overlay value identical to that default) |
| `overlay` | `deploy/ylang.models.json` or `YLANG_MODEL_ALIASES_PATH` **added or remapped** the key (logged at INFO) |
| `prefix` | No exact table hit; a prefix compatibility rule fired |

**Authoritative defaults:** `src/ylang/core/model_aliases.py`
(`DEFAULT_CURSOR_SLUG_ALIASES`). The bundled `deploy/ylang.models.json` must
match that table exactly (enforced by tests). Identical overlay values are
silent. Adds and remaps are logged so a live overlay cannot silently diverge.
Override the overlay path with `YLANG_MODEL_ALIASES_PATH` (restart required).

## Resolution reasons

Every completion persists a `ModelResolution` inside `routing_reason_json`:

| Field | Meaning |
|-------|---------|
| `requested_model` | Client/model argument as received (or null) |
| `requested_alias` | Set when a compatibility mapping fired |
| `alias_source` | `builtin` / `overlay` / `prefix` when an alias fired |
| `semantic_route` / `resolved_route` | Activity bucket (`code`, `search`, …) |
| `selected_provider` | LiteLLM prefix actually used (`anthropic`, `ollama`, …) |
| `selected_model` | Concrete LiteLLM route that answered (or was selected) |
| `resolution_reason` | Machine-readable code (below) |
| `attempt_index` | Position in the attempt chain (`0` = first try) |

| `resolution_reason` | Meaning |
|---------------------|---------|
| `activity_default` | Normal policy pick from the activity candidate list |
| `operator_override` | Console/runtime `models_*` list differs from process baseline (env at router construction) |
| `compatibility_alias` | Legacy/client slug mapped to a current route |
| `explicit_model` | Caller passed a LiteLLM `provider/model` string |
| `quality_preference` | Reordered by recent success / improver-accepted counts |
| `cost_tiebreak` | Known cheaper LiteLLM unit cost within `YLANG_QUALITY_BAND` (unknown/`0.0` cost is never treated as free) |
| `provider_unavailable` | Preferred candidate skipped (no key); next candidate used |
| `provider_cooldown` | Preferred candidate cooling down; next candidate used |
| `budget_fallback` | Daily spend cap forced local-only |
| `local_fallback` | No usable cloud candidate; configured local floor |

`steps[]` remains the ordered decision audit (configured preference, cooldown,
runtime fallback events, …).

## Console presets

Parameters page chips / Fast|Quality buttons:

- **fast** — `mistral/mistral-small-latest,anthropic/claude-haiku-4-5`
- **quality** — `anthropic/claude-sonnet-5,openai/gpt-5.5` (improve full quality preset adds Medium/Small Mistral)

These rewrite the activity candidate list. The semantic route name does not change.

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

Hard constraints first, then evidence, then safe fallback:

1. Resolve semantic activity (`code` / `search` / `reason` / `improve` / `other`)
2. Load candidate list (defaults ← env ← runtime)
3. Preference reorder from recent usage success (skipped for `improve`)
4. Daily budget filter (drop cloud when over `YLANG_DAILY_BUDGET_USD`)
5. Availability (API key + provider cooldown)
6. Quality-band cost tie-break via `select_from_quality_band()` — only **known**
   LiteLLM unit costs (`> 0`) compete; missing/`0.0` cost stays in quality order
7. Attempt chain: optional explicit/alias model → selected → remaining available → local fallback floor

Runtime list edits (Parameters `models_code` etc.) that differ from the
process baseline are recorded as `resolution_reason=operator_override` after
hard constraints / quality / known-cost tie-break. Env-file `YLANG_MODELS_*`
at startup is the baseline, not an override.

Ylang does not invent latency or quality scores it does not collect. Preference
reorder uses existing success / improver-accepted counts only.

Full env reference: [configuration.md](configuration.md). Gateway passthrough: [gateway.md](gateway.md). Optional OTLP export: [configuration.md](configuration.md#opentelemetry-otlp).
