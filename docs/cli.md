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

## `ylang prompts`

Prompt intelligence: allowlisted source refresh and candidate review. Public
prompts are never auto-promoted. See [prompt-intelligence.md](prompt-intelligence.md).

```bash
ylang prompts sources list
ylang prompts sources enable prompts-chat
ylang prompts refresh prompts-chat
ylang prompts refresh --all              # due enabled sources; skips interval
ylang prompts refresh --all --force
ylang prompts candidates list
ylang prompts candidates show prompts-chat:character
ylang prompts candidates diff prompts-chat:character
ylang prompts candidates reject <id>
ylang prompts candidates promote <id>
ylang prompts candidates evaluate <id> [--vs TEMPLATE] [--fixture-file PATH]
ylang prompts candidates evaluate <id> --mode execute --simulated --vs T --fixture-file F
ylang prompts candidates evaluate <id> --mode execute --authorize-paid --budget-usd 0.5 --model M --vs T --fixture-file F
ylang prompts metrics
```

High-risk candidates require `--acknowledge-risk`. `--all` refreshes only
**enabled** scheduled sources whose interval is due (`manual-import` is never
included). Default `evaluate` is **inspect** (zero paid calls). `--mode execute`
without `--authorize-paid` / `--simulated` is refused. Incompatible sources
cannot be enabled. See [prompt-intelligence.md](prompt-intelligence.md) and
[evaluation-methodology.md](evaluation-methodology.md).

## Related docs

- [Configuration](configuration.md) — env vars and routing
- [Models](models.md) — default lists and aliases
- [Deployment](deployment.md) — systemd and HTTP transport
- [Portal](portal.md) — browser operator UI
