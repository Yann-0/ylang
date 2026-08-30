# Y2 — Explainable Model Routing and Policy

**Builds on:** `core/model_router.py`, `core/engine.py`, budget/preference seams  
**Does not invent:** an ML router unless later evidence demands it

## Goal

For every routed call, Ylang can explain at an appropriate level:

> Selected model **X** because …

…without leaking secrets (API keys, full auth headers, raw provider credentials).

## Current deterministic policy (as implemented)

Order of effect on the attempt chain:

1. **Activity bucket** — map activity / `improve:*` → configured list  
2. **Configured preference** — env / runtime activity model lists  
3. **Learned preference** — `apply_preference_order` (skipped for pure `improve` bucket)  
4. **Budget constraint** — `apply_budget_filter` drops cloud when 24h spend ≥ cap  
5. **Provider unavailable** — missing key → `skipped:no_key`  
6. **Cooldown** — retryable failure → `skipped:cooldown`  
7. **Quality band + cost tie-break** — among available within band, min estimated unit cost  
8. **Explicit user/client override** — `explicit_model` prepended when resolvable  
9. **Fallback floor** — local default (e.g. `ollama/qwen2.5`) always appended  

Startup already prints `format_routing_report()`. **Per-request persistence is the gap.**

---

## Reason taxonomy (must distinguish)

| Code | Meaning | Example text (safe) |
|------|---------|---------------------|
| `configured_preference` | Rank from configured activity list | “First available in `models_code` order” |
| `learned_preference` | Reordered by usage success / improver_accepted | “Boosted by 24h accept/success counts” |
| `budget_constraint` | Cloud stripped due to daily budget | “Over daily budget; local-only candidates” |
| `provider_unavailable` | No key / provider not configured | “Skipped openai: no key” |
| `cooldown` | Provider cooling down after retryable errors | “Skipped anthropic: cooldown” |
| `explicit_override` | Client/user forced a model | “Client requested `gpt-4o-mini`” |
| `quality_cost_tiebreak` | Selected among band by estimated cost | “Cheapest within quality_band=N” |
| `fallback` | Reached floor or recovered after failure | “Fell back after retryable error from M1” |
| `fallback_exhausted` | All attempts failed | “No candidate succeeded” |

Multiple codes may apply; store an **ordered list** of decision steps, not a single opaque string.

---

## `routing_reason_json` shape (normative)

```json
{
  "schema": 1,
  "activity": "code",
  "selected": "ollama/qwen2.5",
  "steps": [
    {"code": "configured_preference", "detail": "bucket=code"},
    {"code": "learned_preference", "detail": "reordered_by=improver_accepted"},
    {"code": "budget_constraint", "detail": "spent_usd=1.20 cap_usd=1.00 local_only=true"},
    {"code": "provider_unavailable", "models": ["openai/gpt-4o"]},
    {"code": "quality_cost_tiebreak", "band": 1, "pool": ["ollama/qwen2.5"]},
    {"code": "fallback", "from": "openai/gpt-4o", "to": "ollama/qwen2.5", "error_class": "rate_limit"}
  ],
  "candidates": ["…attempt chain…"],
  "policy": {
    "daily_budget_usd": 1.0,
    "quality_band": 1,
    "fallback_model": "ollama/qwen2.5"
  }
}
```

**Forbidden in JSON:** API keys, Authorization values, raw env dumps, full prompt bodies.

**Allowed:** model slugs, provider names, numeric budget spent/cap, error **classes**, ranks.

---

## Operator-facing explanation levels

| Level | Audience | Content |
|-------|----------|---------|
| One-liner | Console Today / Routing | “Selected `ollama/qwen2.5` because budget_constraint + local fallback” |
| Structured | Trace detail | Full `steps[]` |
| Diagnostic | Doctor / logs | Same as structured + candidate statuses |

## Reproducibility requirement

Given the same:

- activity model lists  
- provider key presence (boolean map, not secrets)  
- cooldown state snapshot  
- budget spent/cap  
- preference count snapshot  
- explicit model  

`build_attempt_chain` + reason builder must produce the **same selected model and reason codes**. Gate: unit tests with frozen clocks / injected cooldown tracker.

## Non-goals for Y2

- Learned neural ranking  
- Auto-tuning activity lists without proposal/apply  
- Cross-tenant shared routing models  

## Implementation tasks

`YLANG-CP-020`… in [06_MASTER_ACTION_PLAN.md](06_MASTER_ACTION_PLAN.md).
