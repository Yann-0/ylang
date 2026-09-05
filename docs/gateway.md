# OpenAI-compatible gateway

Ylang exposes an **OpenAI-compatible HTTP gateway** on the same host, port, and bearer auth as the MCP HTTP transport. Point Cursor (or any OpenAI-compatible client) at it to route real coding traffic through Ylang's activity-based model selection.

The gateway is enabled automatically when `YLANG_TRANSPORT=http`. Startup stderr logs the route paths and virtual model names. **Stdio transport has no `/v1/*` routes** — use HTTP for the gateway.

## Availability

| Transport | MCP | Gateway (`/v1/*`) |
|-----------|-----|-------------------|
| `stdio` (default) | Yes | No |
| `http` | Yes (`/mcp`) | Yes (requires `YLANG_AUTH_TOKEN`) |

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/v1/chat/completions` | Bearer | Chat completions (streaming and non-streaming) |
| `GET` | `/v1/models` | Bearer | Virtual route model catalog |
| `GET` | `/usage` | Bearer | Redirects to `/console/usage` |
| `GET` | `/console` | Bearer | Admin console overview |
| `GET` | `/console/usage` | Bearer | Chart.js usage dashboard (last 7 days; 30s auto-refresh) |
| `GET` | `/health` | None | Service health and version JSON |

All routes share the same HTTP server as MCP (`/mcp`). There is no separate gateway port or process.

## Authorization

HTTP transport requires `YLANG_AUTH_TOKEN`. Bearer auth applies to **`/mcp`, `/v1/*`, `/console`, and `/usage`**:

| Item | Value |
|------|-------|
| Header | `Authorization: Bearer <YLANG_AUTH_TOKEN>` |
| Env var | `YLANG_AUTH_TOKEN` (required when `YLANG_TRANSPORT=http`) |
| Protected paths | `/mcp`, `/v1/chat/completions`, `/v1/models`, `/console`, `/usage` |
| Exempt path | `GET /health` (no bearer token) |
| Missing / wrong token | **401 Unauthorized** (plain text body) |
| stdio transport | No auth — Cursor spawns a local subprocess |

The middleware compares the full `Authorization` header value with constant-time `secrets.compare_digest`. Send exactly `Bearer <token>` with no extra whitespace.

### Optional trace correlation headers

| Header | Effect |
|--------|--------|
| `X-Ylang-Parent-Trace` | Sets `parent_trace_id` on the usage/trace row |
| `X-Ylang-Trace-Id` | Sets this call's `trace_id` (otherwise Engine allocates a UUID) |
| `X-Ylang-Session` | Sets `session_id` on the usage row |
| `X-Ylang-Workspace` | Sets `workspace` on the usage row |

Body aliases `parent_trace_id` / `trace_id` / `session_id` / `workspace` are also accepted. Ylang never invents parent links without an explicit client value.

## GET /health

Unauthenticated liveness probe. Returns JSON with `status`, `version`, and `service`. Exempt from bearer middleware (`mcp/auth.py`).

**Sample response:**

```json
{"status": "ok", "version": "0.4.0", "service": "ylang"}
```

## GET /v1/models

Returns the four virtual route models. Passthrough provider slugs are **not** listed here — clients may still send them in `POST /v1/chat/completions`.

**Sample response:**

```json
{
  "object": "list",
  "data": [
    {"id": "route-code", "object": "model", "created": 1710000000, "owned_by": "ylang"},
    {"id": "route-search", "object": "model", "created": 1710000000, "owned_by": "ylang"},
    {"id": "route-reason", "object": "model", "created": 1710000000, "owned_by": "ylang"},
    {"id": "route-other", "object": "model", "created": 1710000000, "owned_by": "ylang"}
  ]
}
```

## POST /v1/chat/completions

### Request

Required JSON fields:

| Field | Type | Notes |
|-------|------|-------|
| `model` | string | Virtual `route-*` id or passthrough model slug |
| `messages` | array | At least one message; each has `role` (`system`, `user`, or `assistant`) and `content` |
| `stream` | boolean | Optional; default `false`. Set `true` for SSE streaming |

`content` may be a string or an array of `{type: "text", text: "..."}` parts (text parts are joined with newlines).

**Sample non-streaming request:**

```json
{
  "model": "route-code",
  "messages": [{"role": "user", "content": "write hello world in python"}]
}
```

### Non-streaming response

On success (**200**), the body matches OpenAI `chat.completion` shape:

```json
{
  "id": "chatcmpl-abc123...",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "route-code",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 34,
    "total_tokens": 46
  }
}
```

The `model` field echoes the **client request model** (e.g. `route-code`), not the LiteLLM model that actually served the call.

Errors use OpenAI-style `{ "error": { "message", "type", "param?", "code?" } }` JSON. Common cases:

| Status | When |
|--------|------|
| 400 | Invalid JSON, missing `model`/`messages`, bad message shape |
| 401 | Missing or wrong bearer token |
| 404 | All models in the attempt chain failed (`code: model_not_found`) |
| 500 | Unexpected server error |

### Streaming

Set `"stream": true`. The response is `text/event-stream` with OpenAI-style SSE chunks:

```text
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

If the model chain fails before any content is emitted, the handler returns **404** JSON instead of an SSE stream. Partial stream failures after content has started terminate with a final chunk and `[DONE]`.

## Virtual route models

| Model id | Engine activity | Routing |
|----------|-----------------|---------|
| `route-code` | `code` | Quality-first list for coding tasks |
| `route-search` | `search` | Search-oriented models |
| `route-reason` | `reason` | Reasoning / planning models |
| `route-other` | `other` | General fallback bucket |

Each virtual model triggers **activity routing**: the Engine picks the best available model from the configured list for that activity (see [configuration.md](configuration.md)), then walks the fallback chain on failure.

Gateway traffic does **not** run the improver (`improver_fired=False`).

## Passthrough model names

Any `model` string that is **not** a virtual `route-*` id is treated as an explicit passthrough:

1. The gateway maps it to `activity=other` and passes the raw string to the Engine as `explicit_model`.
2. `ModelRouter.resolve_explicit_model()` translates it to LiteLLM form when possible:
   - Cursor / local aliases first (e.g. `gpt-4o-mini` / `ollama/gpt-4o-mini` → `ollama/qwen-coder-14b`, `claude-sonnet-4-6` → `anthropic/claude-sonnet-5`, `gpt-5.5-medium` → `openai/gpt-5.5`)
   - Already LiteLLM-routable: `provider/model` (e.g. `openai/gpt-5.5`, `anthropic/claude-opus-5`, `mistral/mistral-medium-latest`, `gemini/gemini-3.7-flash`, `ollama/qwen2.5`)
   - Prefix rules: `claude-sonnet-4|5-*` → `anthropic/claude-sonnet-5`, `claude-opus-4|5-*` → `anthropic/claude-opus-5`
   - Unrecognized slugs: warning logged; activity routing proceeds without the explicit model

   **Note:** An Ollama tag named like an OpenAI model (`gpt-4o-mini`) must be aliased to a non-colliding LiteLLM id. Otherwise LiteLLM routes through the OpenAI client and Cursor shows *User Provided API Key Rate Limit Exceeded* when the cloud key is throttled.
3. The attempt chain tries the resolved explicit model first, then the activity-selected model, then remaining candidates, then the fallback floor (`ollama/qwen2.5` by default).

See [models.md](models.md) for the full alias and default-list tables.

## Request flow

```mermaid
sequenceDiagram
    participant Client as Cursor / OpenAI client
    participant Auth as BearerTokenMiddleware
    participant GW as gateway/routes.py
    participant Map as gateway/mapping.py
    participant Eng as core/engine.py
    participant Rtr as model_router
    participant LLM as LiteLLM
    participant DB as usage store

    Client->>Auth: Authorization: Bearer token
    Auth->>GW: POST /v1/chat/completions
    GW->>Map: resolve_gateway_model(model)
    alt route-code / route-search / ...
        Map-->>GW: activity + no explicit model
    else passthrough e.g. ollama/qwen2.5
        Map-->>GW: activity=other + explicit model
    end
    GW->>Eng: complete() or complete_stream()
    Eng->>Rtr: build_attempt_chain
    Eng->>LLM: completion (all providers via LiteLLM)
    Eng->>DB: write_usage (surface=gateway)
    GW-->>Client: OpenAI JSON or SSE chunks + [DONE]
```

## Cursor setup

### Cursor Agent chat cannot use a private gateway

Ylang is deliberately **not** reachable from the internet: it binds the LAN only and no port is forwarded. Cursor routes BYOK model calls through **its own cloud**, which refuses private address space:

```text
Provider returned error: Access to private networks is forbidden
```

So `http://192.168.1.25:8787/v1`, `http://stelsrv-d001:8787/v1`, and `http://127.0.0.1:8787/v1` all fail for Agent/chat no matter how reachable they are on your LAN. Keeping Ylang private and routing Cursor Agent chat through it are mutually exclusive — that is a Cursor constraint, not something Ylang can work around.

A related symptom: when the Base URL is unusable, Cursor silently falls back to api.openai.com with your `sk-…` key and reports *User Provided API Key Rate Limit Exceeded*. That message looks like a quota problem but means "Cursor never reached your endpoint". Malformed values cause the same thing:

| Value | Result |
|-------|--------|
| `http://<host>:11434,` | Ollama's own port, trailing comma, no `/v1` |
| `http://<host>:8787` | missing `/v1` |
| `http://<host>:8787/v1/chat/completions` | Cursor appends the path itself |

### What does work while staying private

| Surface | Status |
|---------|--------|
| MCP improver + hooks (`/mcp`) | works — Cursor's MCP client runs on the host, so `127.0.0.1` is fine |
| Console (`/console`) | works over LAN |
| CLI (`ylang …`) | works |
| `/v1/*` from LAN clients (scripts, local IDEs, LiteLLM, Continue) | works |
| Cursor Agent/chat via `/v1/*` | **not possible** without a public origin |

Use the MCP improver for Cursor and point LAN-local OpenAI-compatible clients at `http://<host>:8787/v1` with a Bearer token.

If you ever decide to accept a public origin, it needs a hostname with valid TLS on port 443 (a bare public IP fails certificate validation) — but that is out of scope here by design.

**Notes:**

- Browser `Unauthorized` on `/v1` is normal (no Bearer). Use Cursor’s API key field or `curl -H "Authorization: Bearer …"`.
- Ollama's own OpenAI-compatible port (`11434`) bypasses Ylang entirely — no routing, no usage rows, no aliases. Always point at `8787`.
- Tab/autocomplete typically stays on Cursor's built-in models; the gateway captures chat/agent requests you explicitly route.
- MCP (`/mcp`) and the gateway (`/v1/*`) share auth and the same process.
- **First-party Cursor models (Grok, Composer):** enabling OpenAI API Key / Override OpenAI Base URL causes `Bad Request — This model does not support custom API keys`. Turn the override off (or `Ctrl+Shift+0`) before using Grok/Composer; see [cursor-integration.md — First-party models vs Ylang gateway](cursor-integration.md#first-party-models-vs-ylang-gateway).

See also [cursor-integration.md](cursor-integration.md) for MCP and hook setup (complementary to gateway routing).

## Examples

### Health check (no auth)

```bash
curl -s http://127.0.0.1:8787/health
```

### Auth check (expect 401)

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://127.0.0.1:8787/v1/chat/completions -d '{}'
```

### Virtual model list

```bash
curl -s http://127.0.0.1:8787/v1/models \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Routed completion

```bash
curl -s http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"route-code","messages":[{"role":"user","content":"write hello world in python"}]}'
```

### Passthrough completion

```bash
curl -s http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"ollama/qwen2.5","messages":[{"role":"user","content":"hi"}]}'
```

### Streaming

```bash
curl -N http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"route-code","stream":true,"messages":[{"role":"user","content":"hi"}]}'
```

After a successful request, `usage_summary` should show a row with `surface=gateway` and the matching activity (e.g. `code` for `route-code`).

### Usage dashboard

When `YLANG_TRANSPORT=http`, open `GET /console` or `GET /console/usage` (same bearer auth as gateway routes) for the admin console and Chart.js usage dashboard. Legacy `GET /usage` redirects to `/console/usage`.

Alternatively, generate a standalone file:

```bash
ylang usage dashboard --output /tmp/ylang-usage.html --last-days 7
```

## OpenAI parity limits

The gateway implements enough of the OpenAI chat API for Cursor routing. Known gaps:

| Field | Behavior |
|-------|----------|
| `usage.completion_tokens` | From LiteLLM usage metadata (non-streaming) |
| `usage.total_tokens` | `prompt_tokens + completion_tokens` (non-streaming and streaming final chunk) |
| Streaming token counts | Emitted in final SSE chunk when LiteLLM includes usage (`stream_options.include_usage`) |
| `tools` / `tool_choice` | Forwarded to LiteLLM on streaming and non-streaming requests |
| Streaming tool calls | `tool_calls` deltas emitted in SSE chunks; finish reason `tool_calls` |
| `/v1/models` catalog | Lists virtual `route-*` models only; passthrough slugs are accepted but not advertised |

## Related docs

- [Architecture](architecture.md) — one core, multiple faces
- [Configuration](configuration.md) — model lists per activity
- [Deployment](deployment.md) — HTTP transport and systemd
- [Cursor integration](cursor-integration.md) — MCP and hooks
