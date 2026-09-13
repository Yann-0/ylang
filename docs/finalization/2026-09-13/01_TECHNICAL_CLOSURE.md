# 01 — Technical closure

Implemented on branch `fix/prompt-intelligence-closure-20260913` from HEAD
`475a028` without rebuilding library/gateway/importer/experiments.

## Sources

- `compatibility_status`: `unverified` | `eligible` | `incompatible`
- `github-awesome-copilot` seeded incompatible; `set_enabled(True)` refused
- Adapter still ignores `agents/`, `skills/`, `instructions/`, `mcp`
- Manual refresh may re-verify; scheduled `--all` skips incompatible/disabled

## Fail closed

- `license_policy_error`: unknown/missing/unsupported SPDX blocks scheduled ingest
- Truncated GitHub trees → `SourcePolicyError("truncated")`
- Incomplete file fetch → no ingest, no `removed_upstream`
- Parser errors (`errors > 0`) skip deletion marking
- In-process lock + `prompt_refresh_leases` (TTL 600s)
- `--all` honors `refresh_interval_hours`; `--force` bypasses
- `MAX_INGEST_ITEMS = 200_000` (no silent truncation)

## Evaluation

- `evaluate_candidate` = inspect (zero provider calls)
- `execute_candidate_evaluation` uses Engine/`Completer` on matched fixtures
- Default budget 0; paid requires `--authorize-paid` and `--budget-usd > 0`
- `--simulated` proves mechanics only
- Tools never granted; candidates never promoted by evaluate
- Runs stored in `prompt_evaluation_runs`

## Attribution

- `measure_template(..., version=, since=)` counts only matching `template_version`
- Unversioned usage stays unknown
- Metrics deltas use promote baseline version + `captured_at` window
- Observational vs controlled/simulated labeled on the row

## Schema

Migration **16** `prompt_intelligence_fail_closed`:

- `prompt_sources.compatibility_status`, `compatibility_note`
- `prompt_refresh_leases`
- `prompt_evaluation_runs`

Existing v0.6+ databases upgrade in place. No cloud service, vector DB, or
evaluation SaaS.
