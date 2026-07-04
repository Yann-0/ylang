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

Never commit this file. Restrict permissions: `chmod 600 ylang.env`. See [configuration.md](configuration.md) for every variable and [configuration recipes](configuration.md#configuration-recipes).

### Data directory

The SQLite database and WAL files need a writable directory owned by the service user:

```bash
sudo mkdir -p /srv/ylang/data
sudo chown -R ylang:ylang /srv/ylang/data
sudo chmod 750 /srv/ylang/data
```

Or use the provided script (as root):

```bash
sudo deploy/setup-data-dir.sh /srv/ylang/data
```

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
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:8787/mcp
```

Startup stderr (journalctl) shows transport, storage path, tools, gateway routes, and LLM routing:

```bash
sudo journalctl -u ylang -n 50 --no-pager
```

## Permissions troubleshooting

| Error | Fix |
|-------|-----|
| `SQLite storage is not writable` | `sudo chown -R ylang:ylang /srv/ylang/data` |
| `Operation not permitted` on kill/fuser | Expected — use `systemctl restart ylang` |
| `port 8787 already in use` | Stop duplicate instance; only one HTTP server per port |
| `YLANG_AUTH_TOKEN is required` | Set token in env file before starting HTTP transport |

## Backup

Back up the SQLite file (and `-wal`/`-shm` if present):

```bash
sqlite3 /srv/ylang/data/ylang.db ".backup /backup/ylang-$(date +%F).db"
```

Stop the service or use SQLite online backup for consistency under load.

## Related docs

- [Configuration](configuration.md) — all environment variables, model prioritization, routing recipes
- [Cursor integration](cursor-integration.md) — hooks using HTTP MCP
- [Installation](installation.md) — venv and editable install
