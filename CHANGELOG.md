# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Optimize Ylang wizard** on Operator Hub (`#optimize-wizard`) — diagnose → propose → apply → measure
- **Parameters** — pending runtime proposals embed (Apply with `return_to=/console/settings`), `pattern_detector` select, preferred-template checkbox chips, Impact estimate subtitle
- **Templates** — `toxic=1` filter and **Quarantine toxic** via `POST /console/templates/archive-toxic`
- **Edit feedback dual gate** — hook `_should_capture_edit_feedback` (`YLANG_CAPTURE_EDIT_FEEDBACK` / alias `YLANG_EDIT_FEEDBACK`); `sessionStart` defaults capture to `1`
- **Operator Hub** (`/console/control`) — KPI cards (accept, latency, budget, cost), zero-accept template alert, top applyable proposals, quick links to Parameters / Data / Improver sandbox
- **Facts onboarding CTA** on Hub when total or per-workspace facts are sparse (&lt;3), with links to Facts / suggest
- **Applyable-first proposals** — non-applyable optimizer items demoted (`validation`/`template_revision` → low); Hub sorts applyable high-priority first
- **Polish & performance ratios** — Hub / Overview / Improver KPIs + MCP `improver_analytics` (`polish_ratio` from edit feedback; `performance_ratio` = accept × latency vs 8s target)
- **`ylang-off` improver bypass** — put `ylang-off` or `/ylang-off` anywhere in a Cursor chat message to skip `beforeSubmitPrompt` improvement; marker is stripped from the submitted prompt
- **Parameters studio** (`/console/settings`) — sectioned Routing / Improver / Limits / Flags with env-default vs runtime override badges; nav label **Parameters**
- **Data domain views** — Usage / Templates / Facts / Feedback / Cache / Audit shortcuts above raw table browse
- **Retrieval hard-block** — templates with 0% accept and ≥3 injections excluded from improver context (store-backed), even if not yet archived
- **Learned-template quality gate** — reject trivial prompts (`yes`/`what next`/`commit and push`), short bodies, and passthrough copies; console/MCP surface `skip_reason`
- **Improver fast path** — tighter context caps when `improver_timeout_sec ≤ 18`; omit empty context sections; timeout salvage for vague short prompts
- **Local digest desktop notify (BL-009)** — `ylang usage digest --notify` / `--no-notify`; when `usage_digest_enabled` is on, best-effort `notify-send` if `DISPLAY`/`WAYLAND_DISPLAY` is set
- Honest Settings/Ops digest copy (CLI/cron only; no fake in-console push)

### Changed

- **Proposals skip already-applied settings** — `filter_already_applied` drops pending items whose runtime value already matches (or whose proposal id is in `apply_audit_log`); Optimizer / Control / Parameters embeds share this filter
- **Optimizer skips already-applied runtime suggestions** — `generate_optimization_suggestions` omits `runtime_setting` items whose key/value already match SQLite overrides (stops nagging Fast path)
- **Polish kept-as-is capture** — Cursor improve hook records `prompt_edit` when capture is on and the prompt changed: `auto_apply` → distance 0 (kept); otherwise submitted stays original. Hub/Improver expose `polish_kept_as_is_rate`
- **Improver ultra-fast path** — when `improver_timeout_sec ≤ 12`, tighter context caps and `learned_template_limit=0`
- **Anchoring salvage** — casefold + lower fuzzy threshold + medium paraphrase intent check for `change.before`

### Fixed

- **Cursor `gpt-4o-mini` → local Ollama** — alias bare/`ollama/gpt-4o-mini` to `ollama/qwen-coder-14b` (LiteLLM misroutes the OpenAI-colliding Ollama tag through the OpenAI client, which surfaced as Cursor *User Provided API Key Rate Limit Exceeded*); aliases now win over LiteLLM-routable checks
- **Gateway Cursor BYOK** — accept `OPENAI_API_KEY` as an alternate Bearer alongside `YLANG_AUTH_TOKEN`; advertise local Ollama aliases (including `gpt-4o-mini`) on `GET /v1/models`
- **Improver rejection salvage** — timeout grace + short/medium prompt skeleton fallback; fuzzy `change.before` anchoring; empty-`changes[]` / bad-anchor salvage; Hub no longer nags handled validation reasons
- **Applyable template boost** — `retrieval_preferred_template_ids` runtime setting (+ Parameters UI); optimizer boost suggestions for high-accept library templates are applyable
- **`models_improve` honored for improver** — Cursor slugs (`claude-sonnet-4-*`, `composer`, `auto`) defer to activity routing; runtime overrides hot-reload on each completion; preference reorder skipped for the `improve` bucket
- Engine routing refresh no longer overwrites ad-hoc/test routers when `base_settings` is unset
- Version alignment to **0.5.2** (`pyproject.toml`, package docstring, READMEs)
- `docs/mcp-tools.md` lists **17** tools including `search_templates`
- `docs/database-schema.md` migration paragraph matches `core/migrations.py`

## [0.5.2] - 2026-07-12

### Added

- **Governed proposals page** (`/console/proposals`) — explicit Apply for optimization suggestions and experiment winners; SQLite `apply_audit_log`
- **LAN console access docs** — `YLANG_HOST=0.0.0.0`, firewall port 8787, hostname URLs, cookie `path=/`
- **Post-restore reconnect** — console restore attempts SQLite handle refresh; `ylang doctor` warns on version mismatch and login 401
- **Usage data drill-down** — activity links in data browser filter `usage` rows
- **Scheduled digest settings** — `usage_digest_enabled` toggle and `usage_digest_last_at` timestamp in Settings

### Fixed

- Session cookie uses `path=/` and no `Secure` flag on HTTP LAN deployments
- `ylang doctor` reports HTTP bind address, running service version, and console login reachability

## [0.5.1] - 2026-07-12

### Added

- **Template studio** — param editor (name/description/default), version history
- **Improve with AI** on create/edit forms (`POST /console/api/improve-template`)
- **Preview render** with param defaults (`POST /console/api/render-template`)
- **Database restore** from uploaded backup on Ops page

## [0.5.0] - 2026-07-12

### Added

- **Full admin console** with browser login (`/console/login`), session cookie, and logout
- **Template CRUD** — create, edit (new version), delete (non-seed)
- **Facts CRUD** — add, update, delete with correct `private`/`shareable` scopes
- **Data browser** — paginated preview of all SQLite tables
- **Improver analytics page** — funnel by mode + template effectiveness
- **Feedback viewer** — recent `feedback_events`
- **AI config advisor** — `/console/advisor` grounded in live analytics
- **On-demand optimization narrative** — overview no longer calls LLM on every load
- **Pattern detection on POST** — cached results + nav alert badge via `pattern_alert_threshold`
- **Experiment outcomes** — 7-day accept rates, activate/deactivate variants
- **JSON import** in console Ops (shared helper with CLI)
- **Database restore** from uploaded `.db` backup (typed RESTORE confirmation)
- **Settings per-key reset** and inline documentation for hot-reload keys
- **Provider health + hook log** at `/console/health`
- **Setup checklist** at `/console/setup`
- **Local Chart.js** bundle at `/console/static/chart.umd.min.js`
- **`YLANG_AUTH_TOKEN_PREVIOUS`** for token rotation grace period

### Changed

- Unauthenticated `/console/*` requests redirect to login instead of raw 401
- Documentation, backlog, and package version aligned to v0.5.0

## [0.1.0] - 2026-07-11

### Added

- **MCP server** (stdio and HTTP transports) with **11 tools**:
  `improve_prompt`, `save_template`, `recall_template`, `list_templates`,
  `import_public_prompts`, `remember`, `recall_facts`, `recall_usage`,
  `usage_summary`, `detect_patterns`, and `save_learned_template`
- **Quality-first model routing** across four cloud providers (OpenAI, Anthropic,
  Mistral, Perplexity) with activity-based selection, provider cooldown, usage-based
  preference boost, optional daily budget cap, and an **Ollama floor**
  (`ollama/qwen2.5` fallback)
- **OpenAI-compatible HTTP gateway** on the same process as MCP when
  `YLANG_TRANSPORT=http`: `POST /v1/chat/completions`, `GET /v1/models`,
  `GET /usage`, and `GET /health`; virtual route models (`route-code`,
  `route-search`, `route-reason`, `route-other`) for activity-based chat routing
- **HTTP transport with bearer auth** — `YLANG_AUTH_TOKEN` required on `/mcp`,
  `/v1/*`, and `/usage`; `GET /health` is unauthenticated
- **Local template library** — versioned prompts with public CSV import
  (`import_public_prompts`) and learned-template proposals from usage patterns
- **Scoped memory** — user facts via `remember` / `recall_facts`, injected into
  improver context
- **Usage tracking** — every LLM call logged to SQLite with cost, latency, and
  activity; aggregates via `recall_usage` / `usage_summary` and the `GET /usage`
  Chart.js dashboard

[Unreleased]: https://github.com/Yann-0/ylang/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Yann-0/ylang/releases/tag/v0.1.0
