# Evaluation methodology

Ylang separates **inspection**, **observational trends**, and **simulated
execution**. A working runner does not prove a prompt is better.

## Modes

| Mode | Command | Paid calls | Evidence class | What it stores |
|------|---------|------------|----------------|----------------|
| Inspect | `ylang prompts candidates evaluate ID` (default) | none | observational | static risk/quality, body diff, all-time usage trend labeled mixed/unknown, inactive experiment `traffic_pct=0` |
| Execute simulated | `--mode execute --simulated --fixture-file PATH --vs TEMPLATE` | none | simulated | baseline and candidate outputs from the built-in `SimulatedCompleter` |
| Execute paid (unavailable) | `--mode execute --authorize-paid --budget-usd N` | none: refused before dispatch | no executed run | authorization and budget validation errors |

Portal **Inspect vs current (no LLM)** is inspect only. Its safe inspection
control cannot become a paid operation.

## Authorization and budget

Defaults:

- evaluate mode = `inspect`
- `--budget-usd` = `0`
- `--authorize-paid` = off

Paid authorization and a **finite positive** budget are necessary but are not
an enforceable spending bound. The current Engine has no per-attempt cost-bound
and shared reservation contract. Paid evaluation is therefore **unavailable**,
even with valid authorization and budget flags, and fails before invoking the
completer. NaN, infinity, zero, and negative paid budgets are rejected.

A simulated flag cannot bypass this gate with an Engine-shaped or custom
completer. Simulated execution accepts only the built-in local
`SimulatedCompleter`. It never grants tools or promotes a candidate.

Private history is not replayed. Simulation uses only the operator-supplied
`--fixture-file` text. The built-in simulator makes no provider requests.

Atomic reservations against both evaluation and shared daily budgets, enforced
output limits, and complete per-attempt accounting remain future gates before
paid evaluation can be enabled. The existing daily routing budget meter and
fallback diagnostics do not establish those guarantees.

## Execution evidence

Each attempted simulated run retains per-arm `success`, actual `model_used`,
`trace_id` when supplied, tokens, cost, latency, normalized error, and raw
reported error in `evaluator_json.arms`. The top-level `model` remains the
requested model; it does not replace actual response identities. Unavailable
effective generation settings and trace identifiers remain unknown.

Explicit completion success determines the operational status. A failed
completion with empty error text remains a failure; an empty output does not
erase its status. Successful Engine fallback clears the terminal error while
preserving earlier failures in fallback diagnostics.

An authorization abort after an arm was invoked saves partial evidence before
raising an error containing the saved run ID. Unattempted arms stay distinct
from attempted failures. Preflight refusals make no completion call.

`both_completed` describes an operational outcome, not a valid quality
comparison. Simulated runs always record `comparison_valid=false` and the
`simulated_execution` confounder. Different actual response models additionally
record `model_mismatch`. Real comparisons will also need verified effective
generation settings and accounting for fallback/cache differences.

## Attribution

Post-promotion metrics (`promoted_improved` / `regressed` / `pending`) use:

1. the promoted template id
2. the **exact** promoted `template_version`
3. usage rows with `timestamp >= captured_at`
4. `MIN_OUTCOME_SAMPLES = 3` versioned injections

**New improver events** (MCP and Portal) store injections as
`id@version` in `usage.improver_context_templates` (for example `character@2`).
When exactly one template is injected, the scalar `usage.template_version`
column is also set. Multiple injections leave the scalar NULL and rely on
per-id refs so template A's version is never attached to template B.

**Legacy** bare `id` rows (no `@version` and no usable scalar) remain
**unknown**, not evidence for a newly promoted V2. Older versions are
excluded. All-time V1 accept rate is not attached to a newly promoted V2.

Inspect reports may still show an all-time observational trend, labeled
`evidence_class=observational` with confounders (`all_time_window`,
`unversioned_included`).

## Verdicts

Execute evaluator JSON includes:

```json
{
  "verdict": "both_completed | baseline_error | candidate_error | both_error | inconclusive",
  "quality_claim": false,
  "quality_improvement_demonstrated": false,
  "comparison_valid": false,
  "tools_granted": false,
  "promoted": false
}
```

Completion-without-error is not success. Simulated results prove mechanics.
Inconclusive is a valid outcome.

## Limitations

- Historical improver events often omit version (`bare id`); those rows stay
  unknown. New events write `id@version` going forward — this does **not**
  prove quality improvement by itself.
- Fixtures are operator supplied and do not represent private production
  traffic.
- No LLM-as-judge. No automatic promotion from any verdict.
- Live provider execution and quality improvement are **not** demonstrated by
  CI or by the simulator.
- This patch does not add shared budget reservations or an attempt ledger.

## Related

- [Prompt intelligence](prompt-intelligence.md)
- [Control-plane evaluation model](control-plane-evolution/04_EVALUATION_MODEL.md)
- [Database schema](database-schema.md) — `prompt_evaluation_runs`
