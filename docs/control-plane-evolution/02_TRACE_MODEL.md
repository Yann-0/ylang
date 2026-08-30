# Y1 — Canonical Trace Model

**Builds on:** existing `usage` table and migrations (`core/migrations.py`)  
**Does not create:** a separate telemetry database

## Purpose

A **trace** is the control-plane unit of “what happened” for one observable AI action Ylang mediated (completion, improver call, or tool-triggered completion).

Every field below has an explicit purpose. Fields marked **Phase A** are required for first migration; **Phase B** can follow without breaking Phase A readers.

## Design principles

1. **Extend `usage`, don’t fork it.** Prefer additive columns + optional related tables keyed by `usage.id` / `trace_id`.
2. **Backward compatible.** Old DBs upgrade via `schema_migrations`; missing columns read as NULL / defaults.
3. **Privacy by default.** Raw prompt/context capture is off or heavily redacted unless the operator opts in.
4. **One write path.** Engine (and improver outcome updates) remain the writers; faces pass metadata, they do not invent parallel stores.
5. **Explainability without secrets.** Persist reasons and model ids; never API keys, never full Authorization headers.

---

## Canonical trace fields

| Field | Purpose | Source today | Phase |
|-------|---------|--------------|-------|
| `trace_id` | Stable id for this action (UUID) | **Missing** — generate in Engine | A |
| `parent_trace_id` | Link tool/follow-up to parent | **Missing** | A |
| `usage.id` | Existing PK; keep as internal row id | `usage.id` | — |
| `session_id` / `workspace` | Correlate operator or Cursor workspace | Facts have `workspace`; usage does not | B |
| `surface` | Which face: `mcp`, `gateway`, `console`, `cli` | `usage.surface` | — |
| `activity` | Routing bucket / improver mode | `usage.activity` | — |
| `request_timestamp` | When the call started | `usage.timestamp` | — |
| `prompt_template_id` | Template involved (if any) | Partial via `improver_context_templates` | A (normalize) |
| `template_version` | Exact version used | **Missing** | B |
| `prompt_hash` | SHA-256 of normalized prompt (no body) | **Missing** | A |
| `prompt_body_redacted` | Optional redacted body | Truncated `improver_input_sample` only | A (policy) |
| `context_sources` | JSON list: templates, facts scopes, refs | Partial templates CSV | B |
| `memory_fact_ids` | Facts injected (ids only by default) | **Missing** | B |
| `tool_calls_json` | Observable tool call names/ids (not hidden agent thought) | Engine returns tool_calls; **not persisted** | A |
| `mcp_server` | Logical server name (`ylang`) | Implicit | B |
| `mcp_tool` | Tool that triggered work | **Missing** (improver uses activity label) | A |
| `selected_route` | Virtual route or activity route label | Partial (`route-code` → activity) | A |
| `candidate_models_json` | Attempt chain considered | Built in router; **not persisted** | A |
| `selected_provider` | Derived provider name | Derivable from `model_used` | A |
| `selected_model` | Model that answered | `usage.model_used` | — |
| `routing_reason_json` | Structured explain payload (see Y2) | Startup report only | A |
| `fallback_events_json` | Ordered failed attempts + reason class | Logs only | A |
| `prompt_tokens` | Input tokens | `usage.prompt_tokens` | — |
| `completion_tokens` | Output tokens | Engine has it; **not in usage schema** | A |
| `latency_ms` | Wall time | `usage.latency_ms` | — |
| `cost_estimated` | LiteLLM estimate | `usage.cost` | — |
| `cost_actual` | Operator-supplied actual (optional) | **Missing** | B |
| `error_class` | Stable class (timeout, rate_limit, …) | Partial via success=0 | A |
| `error_message_redacted` | Safe error text | Engine `error`; **not stored** | A |
| `result_status` | `success` / `error` / `cancelled` | `usage.success` bool | A (enrich) |
| `outcome_json` | Improver + client outcome bag | Improver columns today | A (normalize) |
| `evaluation_json` | Scores / labels from eval model | **Missing** | B |
| `policy_decision_json` | Budget/cooldown/override decisions | Implicit in chain | A |
| `capture_level` | Which privacy tier was applied | **Missing** | A |
| `retention_until` | Optional expiry timestamp | **Missing** | B |

---

## Suggested schema strategy

### Migration N+1 — `usage_trace_columns` (Phase A)

Additive `ALTER TABLE usage ADD COLUMN …` for:

- `trace_id TEXT`
- `parent_trace_id TEXT`
- `prompt_hash TEXT`
- `prompt_body_redacted TEXT`
- `mcp_tool TEXT`
- `selected_route TEXT`
- `candidate_models_json TEXT`
- `routing_reason_json TEXT`
- `fallback_events_json TEXT`
- `tool_calls_json TEXT`
- `completion_tokens INTEGER`
- `error_class TEXT`
- `error_message_redacted TEXT`
- `result_status TEXT`
- `policy_decision_json TEXT`
- `capture_level TEXT NOT NULL DEFAULT 'minimal'`

Indexes:

- `idx_usage_trace_id` on `trace_id`
- `idx_usage_parent_trace_id` on `parent_trace_id`

Backfill: leave NULL for historical rows; readers treat NULL as “pre-trace era.”

### Optional related table (Phase B) — `trace_context`

Only if JSON columns on `usage` become unwieldy:

```text
trace_id TEXT PK
context_sources_json TEXT
memory_fact_ids_json TEXT
session_id TEXT
workspace TEXT
```

Prefer columns on `usage` first to keep aggregates simple.

---

## Privacy model

### Capture levels (operator-configurable)

| Level | Persists | Default |
|-------|----------|---------|
| `off` | Metrics only: tokens, cost, latency, model, success, routing reason **codes** (no samples) | No |
| `minimal` | + hashes, template ids, tool names, error class | **Yes (default)** |
| `redacted` | + redacted prompt/body samples under size cap | Opt-in |
| `full_local` | + fuller local bodies (still never leaves host via Ylang cloud) | Explicit opt-in + warning |

### Redaction rules (redacted / full_local)

- Strip bearer tokens, `sk-…`, common API key shapes.
- Truncate to configured max chars (reuse improver sample helper patterns).
- Prefer hash for correlation; body only when needed for debugging.
- Facts: store **ids** by default; fact text only under `full_local`.

### Retention

- Runtime / env: `trace_retention_days` (default e.g. 90 for bodies; metrics may live longer).
- Job (CLI or console): purge `prompt_body_redacted` / high-capture fields past retention; keep aggregates.
- Local-only: no upload API in product scope.

### Sensitive-trace detection (console Privacy)

Heuristic flags (not perfect): high-entropy strings, key-shaped tokens in redacted samples, capture_level ≥ redacted. Surface **count**, not content, on Privacy home.

---

## Write path

```text
Face (MCP / gateway / console)
  → Engine.complete / complete_stream
       → allocate trace_id
       → build_attempt_chain + routing_reason_json
       → LiteLLM attempts (+ fallback_events)
       → write_usage(...trace fields..., capture_level=…)
  → Improver may update outcome_* on same usage row / trace_id
```

Parent/child:

- Gateway tool round-trips: child traces for follow-up completions with `parent_trace_id`.
- MCP `improve_prompt`: single trace; `mcp_tool=improve_prompt`.
- Client-supplied `X-Ylang-Parent-Trace` (optional, Phase B) for agent correlation — never invent hidden agent thoughts.

---

## What Ylang cannot observe (explicit)

- Cursor / agent internal chain-of-thought
- Tools invoked **outside** Ylang faces
- True “user satisfaction” without a signal
- Provider-side billing actuals unless operator imports them

---

## Compatibility contract

- Existing MCP serializers and console queries that read current columns keep working.
- New fields optional in API responses until console wave adopts them.
- Historical rows: `trace_id IS NULL` ⇒ pre-control-plane; dashboards must not crash.

## Implementation tasks

See `YLANG-CP-010`… in [06_MASTER_ACTION_PLAN.md](06_MASTER_ACTION_PLAN.md).
