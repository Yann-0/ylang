# Ylang Console

Server-rendered admin console for local and LAN Ylang HTTP deployments. Open in a normal browser — no Bearer header extension required after login.

Screenshots live under [`images/console/`](images/console/) (captured from a live HTTP instance). Regenerate anytime with:

```bash
# Ylang on :8787; Playwright Chromium installed in the venv
export YLANG_AUTH_TOKEN=…   # or rely on /srv/ylang/ylang.env
/srv/ylang/.venv/bin/python scripts/capture-console-screenshots.py
```

---

## Access

When `YLANG_TRANSPORT=http` and `YLANG_AUTH_TOKEN` is set:

```
http://127.0.0.1:8787/console/login
```

On the same LAN (binding defaults to all interfaces):

```
http://stelsrv-d001:8787/console/login
http://192.168.1.50:8787/console/login
```

Requirements:

- `YLANG_HOST=0.0.0.0` in the service env file (default)
- Port **8787** open on the host firewall for inbound TCP from your subnet
- After code deploy: `sudo systemctl restart ylang` (stale processes return **401** on `/console/login`)

Enter the same token as MCP/gateway. A session cookie (`ylang_token`) is set for 30 days with `path=/`, `SameSite=Lax`, and **no** `Secure` flag (plain HTTP on LAN).

Verify from another machine:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://stelsrv-d001:8787/console/login   # expect 200
curl -s -o /dev/null -w "%{http_code}\n" http://stelsrv-d001:8787/health           # expect 200
```

On the server:

```bash
ylang doctor   # warns if running version ≠ installed package or login returns 401
```

Bearer auth still works for API clients:

```
Authorization: Bearer <YLANG_AUTH_TOKEN>
```

During token rotation, set `YLANG_AUTH_TOKEN_PREVIOUS` to accept both old and new tokens.

---

## Navigation map

| Nav | Route | Role |
|-----|-------|------|
| Overview | `/console` | Health, budget, suggestions, improver sandbox |
| Usage | `/console/usage` | 7-day cost/request charts |
| Improver | `/console/improver` | Funnel + template effectiveness |
| Templates | `/console/templates` | Prompt library studio |
| Facts | `/console/facts` | Local memory for improver context |
| Patterns | `/console/patterns` | Detect repeated prompts → learned templates |
| Experiments | `/console/experiments` | A/B improver system-prompt variants |
| Proposals | `/console/proposals` | Review/apply optimization proposals |
| Feedback | `/console/feedback` | Edit-distance feedback events |
| Data | `/console/data` | SQLite table browser |
| Advisor | `/console/advisor` | LLM Q&A over live analytics |
| Setup | `/console/setup` | Onboarding checklist |
| Settings | `/console/settings` | Hot-reload runtime config |
| Ops | `/console/ops` | Backup / export / import / restore |
| *(linked)* Health | `/console/health` | Provider checks + hook log |

`GET /usage` redirects to `/console/usage` (302).

---

## Login

**Route:** `GET|POST /console/login`

Sign in with `YLANG_AUTH_TOKEN`. Optional `?next=` redirects after success (default `/console`).

![Login screen](images/console/login.png)

| Control | Behavior |
|---------|----------|
| Auth token | Same value as MCP / gateway Bearer token |
| Sign in | Sets `ylang_token` cookie and redirects |
| Logout | `POST /console/logout` from any page nav |

---

## Overview

**Route:** `GET /console`

Landing dashboard: system health, improver KPIs, optimization suggestions, and a live improver preview.

![Overview](images/console/overview.png)

### What you see

| Section | Purpose |
|---------|---------|
| **Cards** | Health, version, configured providers, 24h budget, improver accept %, validated % |
| **AI optimization narrative** | Optional one-shot LLM summary of improver analytics (shown when enough improver traffic exists) |
| **Optimization suggestions** | Propose-only ideas from funnel, validation, templates, and patterns (priority styling) |
| **Test improver** | Paste a rough prompt, pick Cursor mode, preview improved output without leaving the console |

### Related APIs

| Method | Path | Body |
|--------|------|------|
| `POST` | `/console/api/narrative` | Generate narrative (one reason-model call) |
| `POST` | `/console/api/improve-preview` | `{text, mode, tool?, model?}` |

---

## Usage

**Route:** `GET /console/usage`

Rolling **7-day** usage dashboard (Chart.js, local static assets). Auto-refreshes every 30 seconds.

![Usage dashboard](images/console/usage.png)

### Charts & metrics

- Requests, total cost, tokens, success rate
- Improver accept / validation rates
- Cost and requests over time
- Requests by activity and by model
- Daily success rate
- Improver accept rate by Cursor mode
- Top improver rejection reasons

Underlying data comes from the `usage` table (also browsable under **Data**).

---

## Improver

**Route:** `GET /console/improver`

Dedicated improver analytics for the last 7 days.

![Improver analytics](images/console/improver.png)

| Section | Contents |
|---------|----------|
| Summary cards | Accept rate, validation rate, total improver calls |
| By Cursor mode | Fired / accepted / rate / latency per mode (`agent`, `plan`, …) |
| Template effectiveness | Top templates by accept rate when injected into improver context (injections, accept %, avg cost) |

Empty states: *No improver usage yet* / *No template injections yet*.

---

## Templates

**Route:** `GET /console/templates`

Full **template studio**: create, search, paginate, edit (new version), AI-improve, preview render, delete (non-seed), and see lifetime improver **usage** (injection counts).

![Templates studio](images/console/templates.png)

### Create

- Template ID (`[a-z0-9-]+`), name, body with `{param}` placeholders
- Parameter editor (name / description / default)
- Optional AI instruction → **Improve with AI**
- **Preview render** fills defaults into the body
- **Create** saves a new version (`source=user`)

### Browse

| Query param | Description |
|-------------|-------------|
| `q` | Keyword search (FTS hybrid over id, name, body, tags) |
| `source` | `seed`, `user`, or `learned` |
| `sort` | `name`, `id`, `source`, `version`, `usage`, `updated` |
| `order` | `asc` or `desc` |
| `page` | 1-based page |
| `per_page` | `10`, `25`, `50`, or `100` (default `25`) |
| `id` | Open edit panel (`#template-edit`) |

Table columns: ID, Name, Source, Version, **Usage**, Params, Actions (edit / delete icons).

**Usage** = lifetime improver injections (times the template was included in `improve_prompt` reference context). Same signal as Improver effectiveness, without the minimum-sample filter.

### Edit / delete

- Click ID, name, or pencil → edit panel (save new version, AI improve, preview, version history)
- Trash icon deletes non-`seed` templates (confirm dialog)
- Filters preserved via hidden `return_query` on save/delete

### APIs

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/console/templates/save` | Create / new version |
| `POST` | `/console/templates/delete` | Delete non-seed |
| `POST` | `/console/api/improve-template` | `{name, body, params, instruction?}` |
| `POST` | `/console/api/render-template` | `{body, param_values}` |

---

## Facts

**Route:** `GET|POST /console/facts`

Local **memory** for preferences the improver injects into context (stack choices, style rules, conventions).

![Facts studio](images/console/facts.png)

### Add

- Fact text, scope (`private` / `shareable`), optional workspace tag
- **Remember** → PRG redirect; opens edit panel for the new id

### Browse

| Query param | Description |
|-------------|-------------|
| `q` | Keyword over fact, workspace, scope, id |
| `scope` | `private` or `shareable` (invalid values ignored) |
| `workspace` | Substring filter |
| `sort` | `created`, `id`, `fact`, `scope`, `workspace` |
| `order` | default `desc` (newest first) |
| `page`, `per_page` | Same page sizes as Templates |
| `id` | Open edit panel (`#fact-edit`) |

### Empty store

When there are no facts, the page explains the feature and offers **Add sample facts** (`POST /console/facts/seed-samples`) — three starter preferences. Skipped if any facts already exist.

### Mutations

| Method | Path |
|--------|------|
| `POST` | `/console/facts` |
| `POST` | `/console/facts/update` |
| `POST` | `/console/facts/delete` |
| `POST` | `/console/facts/seed-samples` |

Facts are also available via MCP `remember` / `recall_facts` and via Ops export/import.

---

## Patterns

**Route:** `GET /console/patterns`

Detect repeated improver prompts and propose **learned** templates.

![Patterns](images/console/patterns.png)

| Action | Behavior |
|--------|----------|
| **Run pattern detection** | Clusters recent improver inputs; may call the LLM to synthesize template bodies; results cached in runtime settings |
| Pattern cards | Pattern id, occurrence count, sample text |
| Proposal | Suggested template name/body/rationale |
| **Save learned template** | Persists as `source=learned` and redirects to Templates |

Nav badge appears when pattern count ≥ `pattern_alert_threshold` (Settings). Detector mode: `pattern_detector` = `lexical` or `semantic`.

| Method | Path |
|--------|------|
| `POST` | `/console/patterns/run` |
| `POST` | `/console/patterns/save` |

---

## Experiments

**Route:** `GET|POST /console/experiments`

A/B test **improver system-prompt** styles (`control` / `concise` / `verbose`) and review 7-day outcomes.

![Experiments](images/console/experiments.png)

### Create variant

| Field | Meaning |
|-------|---------|
| Experiment ID | Grouping key (default `improver-agent`) |
| Variant ID | e.g. `control`, `variant-a` |
| Config hash | Which system-prompt style to use |
| Traffic % | Share of improver traffic (0–100) |

### Tables

- **Variants** — status + Activate / Deactivate
- **Outcomes (7 days)** — samples, accept rate, validated; ★ marks leader when samples ≥ 5

Enable runtime assignment with Settings → **experiments** (or `YLANG_EXPERIMENTS=1`). Empty table means no variants configured yet — create some with **Upsert variant**.

| Method | Path |
|--------|------|
| `POST` | `/console/experiments` |
| `POST` | `/console/experiments/toggle` |

---

## Proposals

**Route:** `GET /console/proposals`

Review **propose-only** optimization suggestions and apply them explicitly (with audit log).

![Proposals](images/console/proposals.png)

| Section | Purpose |
|---------|---------|
| Pending proposals | Title, kind badge, description, evidence, **Apply** |
| Apply audit log | Last apply actions (time, actor, proposal, detail) |

Empty: *No applyable proposals in the last 7 days.* Apply is never automatic.

| Method | Path |
|--------|------|
| `POST` | `/console/proposals/apply` | `{proposal_id}` |

---

## Feedback

**Route:** `GET /console/feedback`

Inspect edit-feedback events when users change improver output before submit (requires `edit_feedback` / `YLANG_CAPTURE_EDIT_FEEDBACK`).

![Feedback](images/console/feedback.png)

Table (recent events): time, type, edit distance, original snippet, submitted snippet.

---

## Data

**Route:** `GET /console/data`

Read-only SQLite browser for debugging.

![Data browser](images/console/data.png)

| Query | Purpose |
|-------|---------|
| `table` | `usage`, `templates`, `template_versions`, `facts`, `runtime_settings`, `improver_cache`, `feedback_events`, `prompt_experiments`, `apply_audit_log`, … |
| `offset` | Pagination (50 rows/page) |
| `activity` | Filter `usage` by activity |

---

## Advisor

**Route:** `GET|POST /console/advisor`

Ask natural-language questions about improver performance, settings, and templates. Uses live analytics + one LLM call.

![Advisor](images/console/advisor.png)

Enter a question → **Ask advisor** → reply panel. No file changes; advisory only.

---

## Setup

**Route:** `GET /console/setup`

Browser checklist equivalent to parts of `ylang init` / `ylang doctor`.

![Setup](images/console/setup.png)

Checks: Python version, provider keys, auth token, storage path. Links onward to Settings and Health.

---

## Settings

**Route:** `GET|POST /console/settings`

Hot-reload runtime overrides stored in SQLite `runtime_settings` (no process restart for these keys).

![Settings](images/console/settings.png)

### Hot-reloadable keys

- `daily_budget_usd`, `quality_band`, `fallback_model`, `provider_cooldown_seconds`
- `pattern_detector`, `learned_template_limit`, `pattern_alert_threshold`
- `rate_limit_per_minute`
- `models_code`, `models_search`, `models_reason`, `models_improve`, `models_other`
- Feature flags: `improver_critique`, `experiments`, `edit_feedback`
- Digest: `usage_digest_enabled`, `usage_digest_last_at` (updated by `ylang usage digest`)

Use **Reset** next to a field to clear that override back to env defaults. Restart-required env keys (secrets masked) are listed read-only at the bottom.

---

## Ops

**Route:** `GET /console/ops`

Operational maintenance for the SQLite store.

![Ops](images/console/ops.png)

| Action | Endpoint | Notes |
|--------|----------|-------|
| Backup | `GET /console/ops/backup` | Download `.db` |
| Export | `GET /console/ops/export` | JSON (templates + facts) |
| Import | `POST /console/ops/import` | Upload prior JSON export |
| Restore | `POST /console/ops/restore` | Upload `.db` + type `RESTORE` |

CLI equivalents: `ylang backup`, `ylang export`, `ylang import`, `ylang doctor`.

---

## Health

**Route:** `GET /console/health` (linked from Setup)

Provider reachability and Cursor hook log tail.

![Health](images/console/health.png)

Use after deploy or when improver hooks appear stuck.

---

## Console JSON APIs

| Route | Description |
|-------|-------------|
| `POST /console/api/improve-template` | JSON `{name, body, params, instruction?}` — AI-improve template draft |
| `POST /console/api/render-template` | JSON `{body, param_values}` — preview template render |
| `POST /console/api/improve-preview` | JSON `{text, mode, tool, model}` — live improver preview |
| `POST /console/api/narrative` | Generate optimization narrative on demand (one LLM call) |

Session cookie or `Authorization: Bearer` required (same as other console routes).

---

## Static assets

Chart.js is bundled at `/console/static/chart.umd.min.js` (offline-friendly).

---

## Feature flags (quick reference)

| Flag | Where set | Effect |
|------|-----------|--------|
| `improver_critique` | Settings / env | Extra critique pass in improver |
| `experiments` | Settings / `YLANG_EXPERIMENTS` | Assign A/B variants on improver calls |
| `edit_feedback` | Settings / hook env | Capture edit events → Feedback page |
| `usage_digest_enabled` | Settings | Allow scheduled usage digest |
| `pattern_alert_threshold` | Settings | Patterns nav badge threshold |
| `pattern_detector` | Settings | `lexical` vs `semantic` clustering |

---

## Setup wizard (CLI)

```bash
ylang init
```

Web equivalent: `/console/setup` plus `/console/health` for provider and hook checks.

See [installation.md](installation.md) and [configuration.md](configuration.md).
