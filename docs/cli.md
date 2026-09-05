# CLI reference

With no subcommand, `python -m ylang` / `ylang` starts the MCP server (stdio or HTTP per settings).

```bash
ylang                     # MCP server
ylang <subcommand> …      # ops / analytics
```

## `ylang init`

Interactive setup wizard (Python version, Ollama reachability, env hints, optional Cursor `mcp.json`).

```bash
ylang init
ylang init --non-interactive
```

## `ylang doctor`

Checks local environment: storage path writable, provider keys present, fallback model key gate, optional Ollama host.

```bash
ylang doctor
```

## `ylang backup`

Online SQLite backup to a destination file.

```bash
ylang backup --output /path/to/ylang-backup.db
```

## `ylang export` / `ylang import`

Export or import templates and facts as JSON.

```bash
ylang export --output templates-facts.json
ylang import --input templates-facts.json
```

## `ylang purge-traces`

Purge old redacted/full prompt bodies from usage traces (privacy hygiene).

```bash
ylang purge-traces --older-than-days 30
```

## `ylang usage`

Usage analytics over a rolling window (`--last-days` or `--last-hours`).

| Subcommand | Purpose |
|------------|---------|
| `summary` | Aggregated usage statistics |
| `digest` | Pretty digest; optional `--notify` / `--no-notify` for Linux `notify-send` |
| `dashboard` | Static HTML dashboard (`--output`, default `/tmp/ylang-usage.html`) |
| `improver-report` | Improver funnel and template effectiveness |

```bash
ylang usage summary --last-days 7
ylang usage digest --last-days 1 --notify
ylang usage dashboard --output /tmp/ylang-usage.html
ylang usage improver-report --last-days 14
```

## `ylang patterns`

Detect repeated improver usage and propose/save learned templates.

| Subcommand | Purpose |
|------------|---------|
| `suggest` | Show learned template proposals (`--window-days`, default 30) |
| `apply` | Save a learned template from a proposal |

```bash
ylang patterns suggest --window-days 30
ylang patterns apply --window-days 30 --index 0
```

See `ylang patterns apply --help` for exact flags.

## Related docs

- [Configuration](configuration.md) — env vars and routing
- [Models](models.md) — default lists and aliases
- [Deployment](deployment.md) — systemd and HTTP transport
- [Console](console.md) — browser operator UI
