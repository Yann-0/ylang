# Evaluation methodology

Ylang separates **inspection**, **observational trends**, **simulated
execution**, and separately authorized **controlled execution**. A working runner does not prove a prompt is better.

## Modes

| Mode | Command | Paid calls | Evidence class | What it stores |
|------|---------|------------|----------------|----------------|
| Inspect | `ylang prompts candidates evaluate ID` (default) | none | observational | static risk/quality, body diff, all-time usage trend labeled mixed/unknown, inactive experiment `traffic_pct=0` |
| Execute simulated | `--mode execute --simulated --fixture-file PATH --vs TEMPLATE` | none | simulated | baseline and candidate outputs from the built-in `SimulatedCompleter` |
| Execute native (disabled by default) | `--mode execute --authorize-paid --budget-usd N --model PIN` | only with separate native activation, policy and sufficient paired reservations | controlled for actual transport; simulated for fixtures | exact native/request/response and conservative tariff evidence; no quality claim |

Portal **Inspect vs current (no LLM)** is inspect only. Its safe inspection
control cannot become a paid operation.

## Authorization and budget

Defaults:

- evaluate mode = `inspect`
- `--budget-usd` = `0`
- `--authorize-paid` = off

Native providers are **disabled by default**. Explicit environment activation
cannot replace canonical monetary authority. A closed catalog supports the five
configured activity chains, JSON improvement and buffered SSE; unsupported
models, paid tools and richer output schemas refuse before transport. See
[Bounded providers](bounded-providers.md) for pinned identities, native wire
contracts, tariff expiry, conservative money bounds and separate live gates.
Local Ollama uses a trusted unmetered loopback daemon; cloud variants are refused.

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
simulated. Fixture native transports are also labeled simulated. No request payload can register a provider or grant monetary authority.

For a bounded comparison, both arms reserve their maximum charge in
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
text. Native conformance and paid canaries were not run by offline qualification;
they require separate approval. Authentication flags alone cannot authorize a
model whose tariff has expired or a request without reserved capacity.

## Execution evidence

Each attempted run retains per-arm `success`, actual `model_used`,
`trace_id` when supplied, tokens, cost, latency, normalized error, and raw
reported error in `evaluator_json.arms`. The top-level `model` remains the
requested model; it does not replace actual response identities. Unavailable
effective generation settings and trace identifiers remain unknown for the built-in simulator. Bounded synthetic arms retain their exact configuration, reservation, integer charge and pricing/request identity. Unknown bounded cost stays null in arm evidence. Native amounts are conservative tariff upper liabilities: `cost_is_upper_bound=true`, `billing_total_known=false`; `billing_upper_bound_known` identifies complete terminal liability evidence. Native usage `cost_actual` stays null. Synthetic exact charge evidence retains its existing classification.

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
- The ledger and native wire/output contracts are qualified with offline transports. Real account availability, invoice pricing and provider conformance remain unverified.
- Abrupt termination can leave durable dispatch intent requiring explicit reconciliation; a timer or lease cannot prove an attempt was free.
- The budget ledger must outlive trace retention. Under an initialized policy, database triggers protect linked usage rows and nonzero legacy-cost rows from deletion on ordinary connections, even with foreign keys disabled. Monetary cost/time fields become immutable; trace payload fields can still be redacted. Deletion protection is conservative at every age until an explicit monetary archival procedure is provided. Backups, migrations, policy activation and any update of the running application require an explicit operator procedure.
- Ylang provider USD and account-wide Codex subscription quota are separate controls.

## Related

- [Prompt intelligence](prompt-intelligence.md)
- [Control-plane evaluation model](control-plane-evolution/04_EVALUATION_MODEL.md)
- [Database schema](database-schema.md) — `prompt_evaluation_runs`
