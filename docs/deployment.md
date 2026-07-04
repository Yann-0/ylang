# Deployment

Ylang can run as a **local subprocess** (stdio MCP) or as a **long-lived HTTP service** suitable for systemd and shared Cursor hook access.

## stdio (development)

Default transport — no extra configuration:

```bash
source .venv/bin/activate
python -m ylang
```

Cursor spawns this process per MCP session. No auth token required.

## HTTP (production / shared)

### Environment file

Create an environment file (example: `/srv/ylang/ylang.env`):

```bash
YLANG_TRANSPORT=http
YLANG_HOST=0.0.0.0
YLANG_PORT=8787
YLANG_AUTH_TOKEN=<generate-with-openssl-rand-hex-32>
YLANG_STORAGE_PATH=/srv/ylang/data/ylang.db

OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

Never commit this file. For a **single admin** on the host, `chmod 600` and owner your login user is enough. When admins run the CLI against the same DB as systemd, use group **`ylang`**: `chown you:ylang ylang.env` and `chmod 640` (see [Shared CLI access](#shared-cli-access)). See [configuration.md](configuration.md) for every variable and [configuration recipes](configuration.md#configuration-recipes).

### Data directory

The SQLite database and WAL files need a writable directory owned by the service user:

```bash
sudo mkdir -p /srv/ylang/data
sudo chown -R ylang:ylang /srv/ylang/data
sudo chmod 770 /srv/ylang/data
```

Or use the provided script (as root):

```bash
sudo deploy/setup-data-dir.sh /srv/ylang/data
```

For **admin CLI access** to the same database, run once as root:

```bash
sudo deploy/setup-cli-access.sh /srv/ylang/data
```

See [Shared CLI access](#shared-cli-access).

### systemd unit

[`deploy/ylang.service`](../deploy/ylang.service) runs Ylang as the `ylang` system user:

```ini
[Service]
User=ylang
Group=ylang
EnvironmentFile=/srv/ylang/ylang.env
ExecStartPre=+/srv/ylang/app/deploy/setup-data-dir.sh /srv/ylang/data
ExecStart=/srv/ylang/.venv/bin/python -m ylang
Restart=always
```

Install and enable:

```bash
sudo cp deploy/ylang.service /etc/systemd/system/ylang.service
# Edit paths in the unit file to match your installation
sudo systemctl daemon-reload
sudo systemctl enable --now ylang
sudo systemctl status ylang
```

After code changes:

```bash
sudo systemctl restart ylang
```

Do **not** run `python -m ylang` manually while the service owns port 8787.

### Hardening notes

The unit file includes:

- `NoNewPrivileges=true`
- `ProtectSystem=strict`
- `ProtectHome=true`
- `ReadWritePaths=/srv/ylang/data`

Adjust `ReadWritePaths` if your data directory differs.

## Client configuration

Point Cursor (or any MCP HTTP client) at the service:

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

For remote access, put a reverse proxy (nginx, Caddy) with TLS in front and restrict by network policy.

### Multi-client HTTP setup

One HTTP Ylang instance can serve multiple Cursor workstations or agents concurrently:

```
┌─────────────┐     ┌─────────────┐
│  Cursor A   │     │  Cursor B   │
│  hooks+MCP  │     │  gateway    │
└──────┬──────┘     └──────┬──────┘
       │    Bearer token    │
       └─────────┬──────────┘
                 v
        ┌────────────────┐
        │ ylang :8787    │
        │  /mcp  /v1/*   │
        │  GET /usage    │
        └────────┬───────┘
                 v
        /srv/ylang/data/ylang.db
```

Each client uses the same `YLANG_AUTH_TOKEN` in MCP headers and gateway `Authorization: Bearer`. Shared SQLite WAL handles concurrent reads; writes (usage rows, templates) serialize safely. For heavy multi-user load, run the [gateway load test](../scripts/gateway_load_test.py) and see [architecture.md](architecture.md#concurrent-gateway-profiling).

| Client | Endpoint | Typical use |
|--------|----------|-------------|
| Cursor MCP | `http://host:8787/mcp` | `improve_prompt`, library tools |
| Cursor gateway | `http://host:8787/v1/chat/completions` | Route agent chat via `route-code` |
| Browser | `http://host:8787/usage` | Usage dashboard (same Bearer token) |

Set `YLANG_HOOK_DISABLED=1` on gateway-only clients to avoid double LLM calls when hooks also run locally.

### OpenAI gateway (Cursor model routing)

The same HTTP service also serves OpenAI-compatible routes:

- `POST /v1/chat/completions` — chat with `route-code`, `route-search`, etc.
- `GET /v1/models` — virtual model catalog

Use the same `YLANG_AUTH_TOKEN` as the API key. Full setup: [gateway.md](gateway.md).

```bash
# Gateway auth (expect 401 without token)
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://127.0.0.1:8787/v1/chat/completions -d '{}'
```

## Health checks

Ylang does not expose a separate health endpoint. Verify the service:

```bash
sudo systemctl status ylang
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:8787/v1/models
```

Expect **200** when the service and token are valid. A bare GET to `/mcp` is not a reliable health probe (MCP uses the streamable HTTP protocol).

Startup stderr (journalctl) shows transport, storage path, tools, gateway routes, and LLM routing:

```bash
sudo journalctl -u ylang -n 50 --no-pager
```

## Permissions troubleshooting

| Error | Fix |
|-------|-----|
| `SQLite storage is not writable` / `StoragePermissionError` | `sudo deploy/setup-cli-access.sh` (adds your user to group `ylang`, fixes data + `ylang.env`) |
| `Operation not permitted` on kill/fuser | Expected — use `systemctl restart ylang` |
| `port 8787 already in use` | Stop duplicate instance; only one HTTP server per port |
| `YLANG_AUTH_TOKEN is required` | Set token in env file before starting HTTP transport |
| `Permission denied` sourcing `ylang.env` as `ylang` | `chown admin:ylang ylang.env` and `chmod 640`, or run CLI as your admin user after `setup-cli-access.sh` |

## Backup

Back up the SQLite file (and `-wal`/`-shm` if present):

```bash
sqlite3 /srv/ylang/data/ylang.db ".backup /backup/ylang-$(date +%F).db"
```

Stop the service or use SQLite online backup for consistency under load.

## CLI against a systemd install

The service unit runs **`/srv/ylang/.venv/bin/python -m ylang`** (MCP server only). Subcommands such as **`ylang usage digest`** and **`ylang patterns apply`** use the same package but are invoked via the **`ylang`** console script in a venv — not via `systemctl`.

| Location | Purpose |
|----------|---------|
| `/srv/ylang/app/.venv` | Editable dev install (`pip install -e .` from `app/`) |
| `/srv/ylang/.venv` | Runtime venv referenced by `deploy/ylang.service` |

Install the wrapper on your login user's `PATH`:

```bash
ln -sf /srv/ylang/app/deploy/ylang-cli ~/.local/bin/ylang
```

### Shared CLI access

Production layout: user **`ylang`** owns `/srv/ylang/data` (mode `750`/`770`). Login user **`yann`** (or other admins) need **group `ylang`** membership and a **group-readable** `ylang.env` to run CLI commands against `YLANG_STORAGE_PATH` without `sudo`.

Run once as root from `app/`:

```bash
cd /srv/ylang/app
sudo deploy/setup-cli-access.sh /srv/ylang/data
# optional: sudo CLI_USERS="yann alice" deploy/setup-cli-access.sh
```

That script:

- Ensures group/user **`ylang`** exist
- Sets **`/srv/ylang/data`** to **`ylang:ylang`** mode **`770`** and SQLite files to **`660`**
- Adds CLI users to group **`ylang`** (`usermod -aG ylang …`)
- Sets **`/srv/ylang/ylang.env`** to **`admin:ylang`** mode **`640`** (systemd reads the env file as root before dropping privileges)

**Start a new login session** (or `newgrp ylang`) so group membership applies, then:

```bash
set -a && source /srv/ylang/ylang.env && set +a
ylang usage digest --last-days 7
ylang patterns apply
```

Manual equivalent (if you cannot run the script):

```bash
sudo groupadd -f ylang    # skip if group exists
sudo usermod -aG ylang yann
sudo chown ylang:ylang /srv/ylang/data
sudo chmod 770 /srv/ylang/data
sudo chown yann:ylang /srv/ylang/ylang.env
sudo chmod 640 /srv/ylang/ylang.env
# refresh group in shell: newgrp ylang
```

Alternative: run one-off commands as the service user (requires **`ylang.env`** readable by **`ylang`**, i.e. mode **`640`** and group **`ylang`**):

```bash
sudo -u ylang bash -c 'set -a; source /srv/ylang/ylang.env; set +a; /srv/ylang/app/deploy/ylang-cli usage digest --last-days 7'
```


## Related docs

- [Configuration](configuration.md) — all environment variables, model prioritization, routing recipes
- [Cursor integration](cursor-integration.md) — hooks using HTTP MCP
- [Installation](installation.md) — venv and editable install
