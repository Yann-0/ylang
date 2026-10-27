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

Paid provider execution remains **unavailable**: the real-adapter registry is
empty. Supplying authorization or a price estimate cannot enable it. Every paid
Engine path requires a trusted bound and canonical shared policy; unsupported
models, paid streaming, tools and structured paid requests refuse before
transport. Known local Ollama execution uses the loopback endpoint; Ollama cloud
variants are refused. This local endpoint is assumed unmetered.

The CLI preserves `--budget-usd` as an exact decimal string. Programmatic bounded
evaluation accepts a decimal string or `Decimal`, rejects binary-float authority,
and floors the cap to integer nano-USD. The old `daily_budget_usd` setting remains
a retrospective routing meter; it cannot create, increase, disable or replace
the canonical SQLite policy. An explicit opening-liability acknowledgement is
required when a policy is initialized. Operator cutover must account for old
in-flight calls and incomplete historic billing; unknown liability is not free.

A simulated flag cannot dispatch an Engine-shaped or custom completer. It
accepts only the built-in local `SimulatedCompleter`. A separate developer
integration path uses the actual Engine with explicitly injected synthetic
adapters. Those adapters freeze text requests, output limits, model/account and
pricing identities, disable caching and hidden retries, and are always labeled
simulated. No runtime setting or request payload registers a real adapter.

For a bounded synthetic comparison, both arms reserve their maximum charge in
one SQLite `BEGIN IMMEDIATE` transaction, against the shared rolling 24-hour cap
and evaluation lifetime cap, before either dispatches. One attempt per arm is
allowed. A failure stops the pair and cancels only provably undispatched arms.
The maximum output ceiling is typed `hard_budget_max_output_tokens` (default
512), loadable from `YLANG_HARD_BUDGET_MAX_OUTPUT_TOKENS` and a validated runtime
override. It is a token ceiling, not a monetary proof. The policy ID is fixed to
`default`; settings cannot switch to a cheaper accounting domain.

The durable ledger records `RESERVED`, fenced `DISPATCHING`, `SETTLED`,
`UNCERTAIN`, `CANCELLED` and `BREACH` attempts. Timeouts, interruptions, missing
usage and process death keep the full hold, even after a rolling-window change.
Only trusted explicit reconciliation releases unknown billing. Charges above a
certified bound freeze further paid admission. Backward UTC movement also
freezes admission. Such a breach is evidence of a failed bound, not a claim that
software prevented an out-of-contract provider bill.

Every actual bounded attempt is retained independently of caller cancellation
or a terminal usage row. The usage insert and internal request link share an
owned transaction; external trace IDs and caller costs are not financial
authority. Legacy unlinked usage and acknowledged opening liabilities remain
counted. Settled charges use dispatch-time attribution for the rolling window;
active/uncertain holds never age out automatically. All writers in one budget
domain must share this canonical database and compatible code. Separate
databases and external provider calls cannot share its aggregate limit.

Private history is not replayed. Execution uses only operator-supplied fixture
text. No supported adapter makes a real provider request. Provider certification,
trusted token/price upper bounds and separately approved provider conformance
checks remain the next gate before real paid evaluation.

## Execution evidence

Each attempted simulated run retains per-arm `success`, actual `model_used`,
`trace_id` when supplied, tokens, cost, latency, normalized error, and raw
reported error in `evaluator_json.arms`. The top-level `model` remains the
requested model; it does not replace actual response identities. Unavailable
effective generation settings and trace identifiers remain unknown for the built-in simulator. Bounded synthetic arms retain their exact configuration, reservation, integer charge and pricing/request identity. Unknown bounded cost stays null in arm evidence; the top-level cost contains known charges only and `billing_total_known` states whether the total is complete.

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
- The ledger and output contract are qualified with synthetic adapters only. No real provider pricing, billing or wire limit is certified.
- Abrupt termination can leave durable dispatch intent requiring explicit reconciliation; a timer or lease cannot prove an attempt was free.
- The budget ledger must outlive trace retention. Backups, migrations, policy activation and any update of the running application require an explicit operator procedure.
- Ylang provider USD and account-wide Codex subscription quota are separate controls.

## Related

- [Prompt intelligence](prompt-intelligence.md)
- [Control-plane evaluation model](control-plane-evolution/04_EVALUATION_MODEL.md)
- [Database schema](database-schema.md) — `prompt_evaluation_runs`
