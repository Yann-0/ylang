# Evaluation methodology

Ylang separates **inspection**, **observational trends**, and **controlled
execution**. A working runner does not prove a prompt is better.

## Modes

| Mode | Command | Paid calls | Evidence class | What it stores |
|------|---------|------------|----------------|----------------|
| Inspect | `ylang prompts candidates evaluate ID` (default) | none | observational | static risk/quality, body diff, all-time usage trend labeled mixed/unknown, inactive experiment `traffic_pct=0` |
| Execute simulated | `--mode execute --simulated --fixture-file PATH --vs TEMPLATE` | none | simulated | baseline and candidate outputs from `SimulatedCompleter` |
| Execute paid | `--mode execute --authorize-paid --budget-usd N --model MODEL --fixture-file PATH --vs TEMPLATE` | yes, capped | controlled | actual Engine outputs, tokens, cost, latency, errors |

Portal **Inspect vs current (no LLM)** is inspect only. Paid execute is CLI-only
so a previously safe inspection control cannot become a paid operation.

## Authorization and budget

Defaults:

- evaluate mode = `inspect`
- `--budget-usd` = `0`
- `--authorize-paid` = off

Paid execute is refused unless both `--authorize-paid` and `--budget-usd > 0`
are set. Spend is tracked on Engine `cost`; exceeding the budget aborts.
Execute never passes `tools` and never promotes.

Private history is not replayed. Only operator-supplied `--fixture-file` text
is sent in execute mode.

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

Execute evaluator JSON always includes:

```json
{
  "verdict": "both_completed | baseline_error | candidate_error | both_error | inconclusive",
  "quality_claim": false,
  "quality_improvement_demonstrated": false,
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
- Controlled execute uses the operator fixture, not the operator's private
  production distribution.
- No LLM-as-judge. No automatic promotion from any verdict.
- Live provider quality is **not** demonstrated by CI. CI uses fixtures and a
  simulated completer.

## Related

- [Prompt intelligence](prompt-intelligence.md)
- [Control-plane evaluation model](control-plane-evolution/04_EVALUATION_MODEL.md)
- [Database schema](database-schema.md) — `prompt_evaluation_runs`
