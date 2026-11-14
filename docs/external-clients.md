# External clients (Claude Code, Codex CLI, Grok)

Ylang integrates with **Claude Code**, **Codex CLI**, and **Grok CLI / Grok bot** the same way: as a **local MCP HTTP server**. Each product keeps its own model backend; Ylang adds tools (`improve_prompt`, templates, facts, usage, …).

Cursor-specific hooks and rules are documented in [cursor-integration.md](cursor-integration.md). This page covers **agents outside Cursor**.

## Prerequisites

Ylang must be running with HTTP transport:

```bash
curl -sS http://127.0.0.1:8787/health
# {"status":"ok","version":"…","service":"ylang"}
```

| Item | Value |
|------|-------|
| MCP URL (same host) | `http://127.0.0.1:8787/mcp` |
| MCP URL (LAN) | `http://<host>:8787/mcp` (e.g. `http://192.168.1.25:8787/mcp`) |
| Auth header | `Authorization: Bearer <YLANG_AUTH_TOKEN>` |
| Optional completions gateway | `http://127.0.0.1:8787/v1` (see [Gateway caveats](#gateway-v1-caveats)) |

Use the same bearer token as in `ylang.env` / systemd `EnvironmentFile`. Never commit the token.

Ylang is **LAN-first**. Do not publish `/mcp` or `/v1` to the public internet just so a vendor cloud can dial in. Prefer a CLI that runs on the same machine (or LAN) as Ylang.

## What “using Ylang” means

| Layer | Claude Code | Codex CLI | Grok CLI / bot |
|-------|-------------|-----------|----------------|
| Model brain | Anthropic | OpenAI / Codex | xAI Grok |
| Ylang MCP tools | Yes | Yes | Yes |
| Cursor-style auto-improve hooks | No | No | No |
| Force all completions via Ylang `/v1` | Unusual | Optional | Usually wrong |

**Recommended default for all three:** MCP only. Ask the agent to call `improve_prompt`, `usage_summary`, or other [MCP tools](mcp-tools.md) when you want Ylang in the loop.

## Claude Code

### CLI

```bash
claude mcp add --transport http ylang http://127.0.0.1:8787/mcp \
  --header "Authorization: Bearer <YLANG_AUTH_TOKEN>"

claude mcp get ylang
```

From another LAN host, replace `127.0.0.1` with the Ylang host IP.

### Config file

Claude Code requires an explicit `"type"` when the entry has a `"url"`. User scope lives in `~/.claude.json` (or use `claude mcp add-json`):

```json
{
  "mcpServers": {
    "ylang": {
      "type": "http",
      "url": "http://127.0.0.1:8787/mcp",
      "headers": {
        "Authorization": "Bearer <YLANG_AUTH_TOKEN>"
      }
    }
  }
}
```

`"type": "streamable-http"` is accepted as an alias for `"http"`.

Verify in-session with `/mcp`, then ask Claude to call `usage_summary`.

## Codex CLI

Put MCP config in **user-level** `~/.codex/config.toml` (not a project `.codex/config.toml` for provider/auth-adjacent keys):

```toml
[mcp_servers.ylang]
url = "http://127.0.0.1:8787/mcp"
bearer_token_env_var = "YLANG_AUTH_TOKEN"
enabled = true
required = true
```

```bash
export YLANG_AUTH_TOKEN='…'   # same value as Ylang service env
```

Static headers are also supported:

```toml
[mcp_servers.ylang]
url = "http://127.0.0.1:8787/mcp"
http_headers = { Authorization = "Bearer <YLANG_AUTH_TOKEN>" }
enabled = true
```

### Optional: Codex completions via Ylang gateway

Only if you intentionally want Codex traffic routed through Ylang’s activity router / LiteLLM:

```toml
# ~/.codex/config.toml (user-level)
openai_base_url = "http://127.0.0.1:8787/v1"
```

Prefer MCP-only unless you need gateway routing. `OPENAI_BASE_URL` as an environment fallback is deprecated/removed in current Codex — use `openai_base_url` in config.

## Grok CLI / Grok bot (xAI)

### CLI (local Grok ↔ local Ylang)

```bash
grok mcp add --transport http ylang http://127.0.0.1:8787/mcp \
  --header "Authorization: Bearer <YLANG_AUTH_TOKEN>"

grok mcp list
grok mcp doctor ylang
```

### Config file

`~/.grok/config.toml` (variable expansion supported):

```toml
[mcp_servers.ylang]
url = "http://127.0.0.1:8787/mcp"
headers = { Authorization = "Bearer ${YLANG_AUTH_TOKEN}" }
```

### Do not point Grok’s model base URL at Ylang

Setting `GROK_BASE_URL` / xAI `base_url` to `http://…:8787/v1` replaces the Grok API endpoint. That does **not** “add Ylang tools”; it hijacks completions. Keep Grok’s API pointed at `https://api.x.ai/v1` and attach Ylang via MCP.

### xAI cloud Remote MCP

Vendor **remote MCP** (cloud Grok calling your server) needs a **public** MCP URL. This project keeps Ylang private/LAN-first — use a **local Grok CLI** on the same host or LAN instead of exposing Ylang.

## Gateway `/v1` caveats

The OpenAI-compatible face (`POST /v1/chat/completions`, `GET /v1/models`) is documented in [gateway.md](gateway.md). Outside Cursor:

- Works for OpenAI-compatible clients that can reach the LAN endpoint **directly**.
- Does **not** run the improver (`improver_fired=False`); MCP `improve_prompt` is separate.
- Bearer auth is required (`YLANG_AUTH_TOKEN`).
- Virtual models: `route-code`, `route-search`, `route-reason`, `route-other`.

Smoke test:

```bash
curl -sS http://127.0.0.1:8787/v1/models \
  -H "Authorization: Bearer <YLANG_AUTH_TOKEN>"
```

## Verify Ylang saw the client

After a successful MCP tool call from any client:

1. `GET /health` still returns ok.
2. Portal usage / MCP surfaces show new rows, or CLI:

   ```bash
   set -a && source /srv/ylang/ylang.env && set +a
   ylang usage digest --last-days 1
   ```

## Related docs

- [Cursor integration](cursor-integration.md) — MCP + hooks inside Cursor
- [Gateway](gateway.md) — `/v1/*` OpenAI face
- [Deployment](deployment.md) — systemd HTTP service
- [MCP tools](mcp-tools.md) — tool reference
- [Configuration](configuration.md) — `YLANG_AUTH_TOKEN`, transport
