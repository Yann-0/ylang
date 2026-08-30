# Y3 — Evaluation Model

**Builds on:** improver outcome columns, `feedback_events`, optimizer, experiments, template effectiveness  
**Does not:** invent a greenfield “feedback” product

## Audit of current signals

### Already present

| Signal | Location | Notes |
|--------|----------|-------|
| Completion `success` | `usage.success` | Provider/call succeeded — not “useful” |
| Latency / tokens / cost | `usage` | Economics + performance |
| `improver_fired` / `accepted` / `validated` / `changed` | `usage` | Improver funnel |
| `improver_rejection_reason` | `usage` | Validation failure class |
| `improver_task_class` | `usage` | structural / analysis / implementation |
| `improver_context_templates` | `usage` | Which templates injected |
| `experiment_variant` | `usage` | A/B arm |
| Prompt edit + Levenshtein | `feedback_events` | User edited after suggestion |
| Template accept rates | analytics / effectiveness | Retrieval may block zero-accept |
| Optimization suggestions | optimizer | Propose-only |
| Experiment winners | proposals | Propose → Apply |
| Fallback / cooldown | logs + in-memory | Not yet first-class eval inputs on rows |

### Missing / weak

- Explicit star/rating UI (optional later)
- Client-supplied task success
- External test/command result linkage
- Normalized evaluation object on the trace
- Treating silence as success (**forbidden**)

---

## Signal taxonomy

Every signal used for optimization or dashboards MUST be classified:

### OBJECTIVE OUTCOME

Observable, machine-checkable results of the call itself.

- Examples: `success=0/1`, HTTP/provider error class, validation pass/fail, latency_ms, token counts, cost, fallback occurred.

### USER SIGNAL

Explicit human judgment or deliberate action.

- Examples: accepted improved prompt (`improver_accepted`), explicit rating (future), Apply/Reject on a proposal, archive template confirmation.

### BEHAVIORAL PROXY

User behavior that *suggests* quality without being labeled success.

- Examples: edit distance after suggestion, retry shortly after, switching models, abandoning improver output (large edit distance).

### HEURISTIC

Rule-of-thumb derived metrics — useful for proposals, never claimed as ground truth alone.

- Examples: “accept rate &lt; 50% over N samples ⇒ trim context”, polish/performance ratios, zero-accept template blocking.

### UNKNOWN

Insufficient evidence; must not drive auto-apply.

- Example: “user did not complain”, missing feedback when `edit_feedback` off, single-sample spikes.

**Rule:** Do **not** treat “user did not complain” as success.

---

## Evaluation object (trace-attached)

Phase B field `evaluation_json` (see [02_TRACE_MODEL.md](02_TRACE_MODEL.md)):

```json
{
  "schema": 1,
  "signals": [
    {"name": "completion_success", "class": "objective", "value": true},
    {"name": "improver_accepted", "class": "user", "value": false},
    {"name": "edit_distance", "class": "behavioral", "value": 42},
    {"name": "accept_rate_window", "class": "heuristic", "value": 0.31, "n": 20}
  ],
  "labels": [],
  "notes": "No client task_success supplied"
}
```

Aggregations for Quality home must show **class** so operators see whether a trend is objective vs proxy.

---

## Experiment model

Compare with shared window + traffic split (existing `prompt_experiments` + outcomes):

| Dimension | Compare |
|-----------|---------|
| Prompt / template versions | template_id@vN vs vM |
| Route policy versions | routing policy hash / reason schema |
| Model A vs B | selected_model distribution + outcomes |
| Cost | mean/p50 cost per success |
| Latency | p50/p95 |
| Quality / outcome | accept rate, validation rate, edit distance, client task_success if present |

### Governance (hard rule)

All optimization that changes production behavior:

**PROPOSE → REVIEW → APPLY**

- Optimizer suggestions and experiment “winners” remain proposals.
- `apply_audit_log` records actor + action.
- **No automatic self-modifying production router** in this program.

Retrieval blocking of proven zero-accept templates is an **existing safety heuristic**; treat as governed policy documented for operators (confirm whether Apply is required for archive — archive already flows through proposals).

---

## Mapping existing optimizer kinds

| Suggestion kind | Primary signal class | Apply path |
|-----------------|---------------------|------------|
| Low accept → trim context | HEURISTIC + USER (accept) | runtime_setting |
| Learned template from pattern | BEHAVIORAL / HEURISTIC | learned_template |
| Archive zero-accept | HEURISTIC + OBJECTIVE samples | archive_templates |
| Experiment winner promote | USER (accept) + OBJECTIVE n | experiment apply |

---

## Implementation tasks

`YLANG-CP-030`… in [06_MASTER_ACTION_PLAN.md](06_MASTER_ACTION_PLAN.md).
