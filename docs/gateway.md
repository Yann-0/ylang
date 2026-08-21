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
   - Cursor / local aliases first (e.g. `gpt-4o-mini` / `ollama/gpt-4o-mini` → `ollama/qwen-coder-14b`, `claude-sonnet-4-6` → Anthropic)
   - Already LiteLLM-routable: `provider/model` (e.g. `openai/gpt-4o`, `anthropic/claude-3-5-sonnet-latest`, `mistral/mistral-large-latest`, `ollama/qwen2.5`)
   - Prefix rules: `claude-sonnet-4-*` → `anthropic/claude-sonnet-4-6`, `claude-opus-4-*` → `anthropic/claude-opus-4-6`
   - Unrecognized slugs: warning logged; activity routing proceeds without the explicit model

   **Note:** An Ollama tag named like an OpenAI model (`gpt-4o-mini`) must be aliased to a non-colliding LiteLLM id. Otherwise LiteLLM routes through the OpenAI client and Cursor shows *User Provided API Key Rate Limit Exceeded* when the cloud key is throttled.
3. The attempt chain tries the resolved explicit model first, then the activity-selected model, then remaining candidates, then the fallback floor (`ollama/qwen2.5` by default).

Provider translation lives in core — the gateway has no provider-specific code.

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

### Base URL must be exact

`Override OpenAI Base URL` is the whole ballgame. A malformed value makes Cursor fall back to api.openai.com with your `sk-…` key, which surfaces as *User Provided API Key Rate Limit Exceeded* — an error that looks like a quota problem but is really a routing problem.

| Value | Result |
|-------|--------|
| `http://<host>:8787/v1` | correct (LAN) |
| `http://<host>:11434,` | **wrong** — Ollama's own port, trailing comma, no `/v1` |
| `http://<host>:8787` | **wrong** — missing `/v1` |
| `http://<host>:8787/v1/chat/completions` | **wrong** — Cursor appends the path itself |

### A LAN URL cannot work

Cursor routes BYOK model calls through **its own cloud**, which refuses private address space:

```text
Provider returned error: Access to private networks is forbidden
```

So `http://192.168.1.25:8787/v1`, `http://stelsrv-d001:8787/v1`, and `http://127.0.0.1:8787/v1` are all dead ends for Agent/chat regardless of local reachability. The gateway needs a **public HTTPS origin**. Port `8787` itself is not forwarded, so it goes through Apache on 443.

### Option A — path on an existing host (no new DNS record)

Reuses a hostname that already resolves, so nothing changes at your registrar:

```bash
sudo /srv/ylang/app/deploy/apache/install-ylang-path-proxy.sh
/srv/ylang/app/deploy/apache/verify-cursor-gateway.sh
```

| Setting | Value |
|---------|-------|
| OpenAI API Key | `YLANG_AUTH_TOKEN` (an `sk-…` key also works — both are accepted) |
| Override OpenAI Base URL | `https://stelliane.dev/ylang/v1` |
| Model | `gpt-4o-mini` (aliased → local Ollama) |

The installer injects a marked block into an existing `*:443` vhost (override with `VHOST=…`), keeps a timestamped backup, and rolls back if `apache2ctl configtest` fails. Only `/ylang/v1/*` and `/ylang/health` are proxied — `/console` and `/mcp` stay off the public host.

### Option B — dedicated subdomain (needs a DNS record)

Prefer a clean hostname? Add the A record yourself (there is no wildcard DNS for `*.stelliane.dev`, though the wildcard TLS cert already covers the name):

```text
ylang.stelliane.dev.  A  <your public IP>
```

```bash
sudo /srv/ylang/app/deploy/apache/install-ylang-vhost.sh
BASE_URL=https://ylang.stelliane.dev/v1 \
  /srv/ylang/app/deploy/apache/verify-cursor-gateway.sh
```

### Confirming it works

Click **Verify** in Cursor, then send a chat. The server must log `POST /v1/chat/completions` and usage must show `model_used=ollama/qwen-coder-14b`. If no request arrives, the Base URL is still wrong — nothing in Ylang can change that.

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
