# 04 — Closure report

Filled after quality gates on 2026-09-13, then extended with versioned
improver injections and large-catalog warnings. Commit/push identity is
filled at the end of this pass.

## Identity

| Field | Value |
|-------|-------|
| Start SHA | `475a028184ab0d4263062a596c415aa7135ce981` (`feat(prompts): ship prompt intelligence ingest and 0.7.0`) |
| Branch | `fix/prompt-intelligence-closure-20260913` |
| Final commit SHA | `8c2fe32e2b177d0c3a9770cc57b067beb78841f9` |
| Package version | `0.7.0` (not bumped; Unreleased in CHANGELOG) |
| Untracked user file preserved | `.cursor/ylang-improved-prompt.md` (not committed) |

## Quality gates

| Check | Result |
|-------|--------|
| `ruff check .` | PASS |
| `pyright` | PASS (0 errors) |
| `pytest -m "not llm_e2e and not network"` | **539 passed**, 5 deselected, 3 warnings |
| `mkdocs build --strict` | PASS |

Paid `--mode execute --authorize-paid` was **not** run. Default CI remains offline.

## Live source identity (rechecked 2026-09-13)

| Source | Upstream SHA | Layout | Verdict |
|--------|--------------|--------|---------|
| `prompts-chat` | `f/prompts.chat` `f78a1c5136fa080155d928e0d7e2b4a41ddef03e` | `prompts.csv` 5 769 655 bytes; **2 169** act/prompt records | **LIVE_SOURCE_VERIFIED** (eligible) |
| `github-awesome-copilot` | `github/awesome-copilot` `7568a482ce2df38f8965ab5336a3220db796a4ba` | 2837 blobs, **0** `*.prompt.md` | **incompatible**; enable refused |
| `fabric-patterns` | `danielmiessler/Fabric` `b682dad740f24e85ce9a48d23babc6780dd476ac` | **255** `data/patterns/*/system.md`, MIT | **LIVE_SOURCE_VERIFIED** (eligible) |

## Follow-up code gaps closed

- New improver events write `id@version` in `improver_context_templates` from
  `Improver.improve` (MCP and Portal). Single-injection also sets scalar
  `template_version`. Multi-injection leaves scalar NULL.
- `measure_template` matches per-id ref versions; legacy bare ids stay unknown.
- Analytics / MCP serializers strip `@version` so ids stay stable.
- Refresh CLI warns when `new + changed + unchanged ≥ 500` (no silent truncate).

## Actual vs simulated

| Kind | Result | Proves |
|------|--------|--------|
| Offline unit tests | inspect + simulated execute + versioned refs | mechanics |
| Live network contracts | layouts + license + parse counts | source compatibility |
| Paid Engine execute | **not run** | — |

Evaluator JSON always stores `quality_improvement_demonstrated: false`.

## Limitations (still honest)

- Live copilot has no v1 prompt files
- Historical bare-id improver events remain unknown
- Controlled execute uses operator fixtures, not private traffic
- Simulated provider ≠ prompt quality
- Versioned writes enable future attribution; they do **not** demonstrate quality

## Remaining blockers (need further authorization)

- Paid provider execute with an operator budget
- Enabling sources in a production database
- Production-traffic experiments or private-history replay
- Release / version bump / tag

## Readiness (separate)

| Gate | Verdict |
|------|---------|
| **LIBRARY_READY** | **yes** |
| **LIVE_SOURCE_VERIFIED** | **mixed** — prompts-chat + Fabric yes; copilot no |
| **EVALUATION_EXECUTION_VERIFIED** | **simulated only** |
| **QUALITY_IMPROVEMENT_DEMONSTRATED** | **no** |
