# Ylang — Open backlog

**Updated:** 2026-07-19 (v0.5.2)  
**Status:** Active — items not yet shipped

Completed work: [backlog-shipped.md](./backlog-shipped.md).

---

## Remaining

| ID | Priority | Title |
|----|----------|-------|
| BL-002 | Low | Full aiosqlite migration (defer until profiling demands) |
| BL-009b | Low | Email (or other remote) digest delivery — desktop notify is local-only |
| BL-010 | Medium | Live improver accept &gt;55% / p50 &lt;8s — Fast/Mistral path live; post-restart n≈4 at ~50% accept / p50~16s. Loop 4 adds ultra-fast (timeout≤12), stronger anchoring, kept-as-is polish. Needs **code reload** (`systemctl restart`) + more post-reload traffic for evidence. |

---

## Shipped in readiness loop 4 (2026-07-19) — BL-010 code levers

| Item | Notes |
|------|-------|
| Ultra-fast path | `improver_timeout_sec ≤ 12` → tighter context; learned templates off |
| Anchoring salvage | Casefold / lower fuzzy ratio / medium paraphrase intent |
| Optimizer de-dupe | Skip runtime suggestions already matching overrides |
| Kept-as-is polish | Hook records distance-0 when `auto_apply` keeps improvement |
| Runtime tune | timeout 12, caches cleared; toxic still 0 |

---

## Shipped in readiness loop 3 (2026-07-19) — Optimize loop & hygiene UI

> **Live in runtime** (post 2026-07-19 ~16:23 UTC restart): Operator Hub Optimize wizard, Parameters pending-proposals embed, toxic quarantine, preferred chips, edit-feedback dual gate, Fast economics → runtime.

| Item | Notes |
|------|-------|
| Optimize wizard | Operator Hub `#optimize-wizard` — diagnose → propose → apply → measure |
| Parameters proposals embed | Pending runtime proposals with Apply (`return_to=/console/settings`) |
| Toxic quarantine UI | Templates `toxic=1` filter, **Quarantine toxic** → `POST /console/templates/archive-toxic` |
| Preferred chips | Checkbox picker for `retrieval_preferred_template_ids` on Parameters |
| Edit feedback dual gate | Hook `_should_capture_edit_feedback` + `sessionStart` default `YLANG_CAPTURE_EDIT_FEEDBACK=1` |
| Fast economics → runtime | Fast/cheap Control proposals applied as runtime settings (hot-reload) |

---

## Shipped in readiness loop 2 (2026-07-19) — Operator Hub & routing truth

| Item | Notes |
|------|-------|
| models_improve routing truth | Cursor slugs defer; hot-reload runtime overrides; no preference reorder on `improve` |
| Zero-accept retrieval hard-block | Store-backed exclusion (≥3 injections, 0% accept) at context build |
| Learned quality gate | Trivial/short/passthrough patterns skipped; `skip_reason` in console/MCP |
| Operator Hub | KPIs + toxic alert + applyable proposals + CTAs |
| Parameters studio | Sectioned settings; nav rename |
| Data domain views | First-class entity shortcuts |
| Improver fast path v2 | Timeout≤18 context caps; empty-section omit; vague-timeout salvage |

---

## Shipped in readiness loop (2026-07-19) — Control Center & hygiene

| Item | Notes |
|------|-------|
| Template `archived` visibility | Excluded from retrieval; console archive/unarchive + bulk unused |
| Zero-accept injection floor | Learned/public with 0% accept (min samples) skipped in retrieval |
| Control Center | `/console/control` — config, inventory, KPIs, governed AI ops |
| Data manager | Search, deep links, clear improver cache, scrub/purge usage |
| Settings presets | Fast/cheap vs Quality; effective vs override hints |
| Nav gating | Experiments/Feedback hidden unless flags on |
| Improver fast path | Lower learned/ref limits; timeout/fast-model suggestions; validation salvage |

---

## Shipped in v0.5.2 — LAN access, proposals, restore polish, digest notify

| Item | Notes |
|------|-------|
| LAN console access | `YLANG_HOST=0.0.0.0`, cookie `path=/`, firewall/docs, `ylang doctor` checks |
| Governed proposals | `/console/proposals` + `apply_audit_log`; explicit Apply only |
| Post-restore reconnect | SQLite handle refresh + restart guidance on Ops page |
| Usage drill-down | Data browser activity links filter `usage` rows |
| Digest settings | `usage_digest_enabled` + `usage_digest_last_at` in Settings |
| **BL-009** local digest notify | CLI/cron digest + optional `notify-send` when DISPLAY available; honest Settings/Ops copy (no fake in-console push) |
| Docs consistency | Package/docs aligned to **v0.5.2**; mcp-tools lists **17** tools incl. `search_templates`; migrations paragraph corrected |

---

## Shipped in v0.5.1 — Template studio & restore

| Item | Notes |
|------|-------|
| Template param editor | Name, description, default — create and edit forms |
| Improve with AI | `POST /console/api/improve-template` + in-form button |
| Preview render | `POST /console/api/render-template` with param defaults |
| Version history | Per-template version table on edit page |
| Database restore | Ops upload with typed RESTORE confirm; safety copy kept |

---

## Shipped in v0.5.0 — Full admin console

| Item | Notes |
|------|-------|
| Browser login + session cookie | `/console/login`, redirect when unauthenticated |
| Template CRUD | Create, edit (new version), delete (non-seed) |
| Facts CRUD | Add, update, delete |
| Data browser | All SQLite tables with pagination |
| Improver analytics page | Funnel + template effectiveness |
| Feedback viewer | `feedback_events` table |
| AI advisor | `/console/advisor` grounded in live analytics |
| Lazy overview LLM | Narrative on demand via API |
| Pattern detection on POST | Cached results + alert threshold badge |
| Experiment outcomes | 7-day accept rates + activate/deactivate |
| Import JSON | Console + shared CLI helper |
| Settings reset per key | Hot-reload overrides |
| Local Chart.js | Bundled under `/console/static/` |
| Provider health + hook log | `/console/health` |
| Setup checklist | `/console/setup` |
| Auth token rotation grace | `YLANG_AUTH_TOKEN_PREVIOUS` |

---

## Shipped — Prompt Usage Analytics & Optimization (PAO-001–014)

See [backlog-shipped.md](./backlog-shipped.md) and [mcp-tools.md](./mcp-tools.md).

---

## BL-004 — Hook respects `auto_apply_default`

**Status:** Shipped (see hook + improver tests).

## BL-005 — Pattern threshold notifications

**Status:** Shipped as console nav badge when occurrences ≥ `pattern_alert_threshold`.

## BL-006 — First-run setup wizard

**Status:** Shipped as `ylang init` CLI + `/console/setup` web checklist.

## BL-007 — Auth token rotation grace period

**Status:** Shipped via `YLANG_AUTH_TOKEN_PREVIOUS` and middleware dual-token support.

## BL-009 — Scheduled local digest notifications

**Status:** Shipped (local) — `ylang usage digest` with optional `notify-send`; Settings/Ops document CLI/cron-only delivery. Remote email remains **BL-009b**.

## BL-002 — Full aiosqlite migration

**Priority:** Low  
**Status:** Open — defer until thread offload is insufficient under load.
