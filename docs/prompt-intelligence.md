# Prompt intelligence

Ylang can refresh a small allowlist of **public prompt catalogs** into a local
**candidate quarantine**. Public text is untrusted until you promote it.

> Refresh automatically; trust manually.

This is not a prompt marketplace, not a Langfuse clone, and not a cloud
service. Ylang stays a local-first personal AI control plane that learns which
prompts actually help **your** workloads.

Canonical strategy (2026-09-12, partially superseded — see below):

- [Prompt intelligence evolution](strategy/YLANG_PROMPT_INTELLIGENCE_20260912.md)
- [Public source policy](strategy/YLANG_PUBLIC_PROMPT_SOURCE_POLICY_20260912.md)

Closure of live-source honesty, fail-closed ingest, bounded Engine evaluation,
and versioned attribution: [finalization 2026-09-13](finalization/2026-09-13/README.md).

## Lifecycle

```text
source → fetch → provenance → normalize → risk scan → dedup → candidate
                                                         ↓
                    inspect (default) or execute (opt-in, budgeted)
                                                         ↓
                              human promote → immutable template version
                                                         ↓
                              versioned observational outcomes (not all-time mix)
```

Internet content never becomes an active template without an explicit
`promote`. Upstream edits of a promoted prompt create `candidate_changed`;
they do not overwrite the local version. Upstream deletions mark
`removed_upstream` **only after a complete successful fetch**. Truncated trees,
partial downloads, parser failures, and license blocks keep last-known-good
candidates.

## Allowlisted sources (Tier A)

Live layout was rechecked on 2026-09-13. A configured adapter is **not** proof
of a working live integration.

| Source id | License | Live status (2026-09-13) | What is imported | Default cadence |
|-----------|---------|---------------------------|------------------|-----------------|
| `prompts-chat` | CC0 1.0 (prompt data; dual-license LICENSE) | **eligible** — `prompts.csv` at `f/prompts.chat@f78a1c5136fa` (2 169 act/prompt records; ~5.7 MiB; 121 758 physical newlines are multiline bodies, not extra prompts) | structured `prompts.csv` | 24h if enabled |
| `github-awesome-copilot` | MIT | **incompatible** — `github/awesome-copilot@7568a482ce2d` has **0** `*.prompt.md` files; tree is agents/skills/instructions | v1 would import `*.prompt.md` only; **will not** convert agents/skills/MCP/instructions into ordinary prompts | cannot enable until a refresh finds eligible files |
| `fabric-patterns` | MIT | **eligible** — 255 `data/patterns/*/system.md` at `danielmiessler/Fabric@b682dad740f2` | `system.md` under `**/patterns/` | 168h if enabled |

Scheduled refresh is **off** until you enable a source. **Incompatible
sources cannot be enabled.** Manual CSV/URL import may still be used; that
URL is **never** registered as a scheduled source.

Expect a sizable candidate set from `prompts-chat` (~2 169 items). Refresh
prints a stderr warning when `new + changed + unchanged ≥ 500`. Ylang does
**not** silently truncate below `MAX_INGEST_ITEMS` (200 000); review before
promoting.

Tier B references (DAIR.AI guide, OpenAI Cookbook, Promptbase, provider docs)
are not bulk-imported.

## CLI (Portal is optional)

```bash
ylang prompts sources list
ylang prompts sources enable prompts-chat
ylang prompts sources disable github-awesome-copilot
ylang prompts refresh prompts-chat
ylang prompts refresh --all          # enabled + due scheduled sources only
ylang prompts refresh --all --force  # ignore per-source intervals
ylang prompts candidates list
ylang prompts candidates show <id>
ylang prompts candidates diff <id>
ylang prompts candidates review <id>
ylang prompts candidates reject <id>
ylang prompts candidates promote <id> [--acknowledge-risk]
ylang prompts candidates evaluate <id> [--vs TEMPLATE] [--fixture-file PATH]
ylang prompts candidates evaluate <id> --mode execute --simulated --vs TEMPLATE --fixture-file PATH
ylang prompts candidates evaluate <id> --mode execute --authorize-paid --budget-usd 0.50 --model MODEL --vs TEMPLATE --fixture-file PATH
ylang prompts metrics
```

`--all` never includes `manual-import`. High-risk candidates require
`--acknowledge-risk`. Promotion creates an immutable `user` template version
with provenance; upstream `tools` metadata is stored, never granted.

### Evaluate modes

| Mode | Default? | Provider calls | Evidence class | Promotion / tools |
|------|----------|----------------|----------------|-------------------|
| `inspect` (default) | yes | **zero** | observational | never |
| `execute --simulated` | no | local fake completer | simulated (mechanics only) | never |
| `execute --authorize-paid --budget-usd N` | no | real Engine / ModelRouter | controlled | never |

`ylang prompts candidates evaluate` without `--mode execute` stays inspect.
Passing `--fixture-file` on inspect still does **not** send text to a
provider. Execute requires fixtures and does not promote or grant tools.

A working evaluation runner does **not** prove a prompt is better.
`quality_improvement_demonstrated` is always `false` unless a later
operator-labeled outcome exists. Inconclusive is acceptable; invented
improvement is not.

## Network / supply-chain

Scheduled fetch is HTTPS-only to `api.github.com` and
`raw.githubusercontent.com` on per-source URL prefixes. Redirects are bounded;
unexpected hosts, oversized payloads, HTML scraping, and remote code
execution are rejected.

Fail closed:

- unknown / missing / unsupported SPDX **blocks** scheduled ingestion
- license text must match the configured SPDX markers
- truncated GitHub trees are a refresh **error**, not an empty success
- incomplete file downloads do not ingest and do not mark `removed_upstream`
- per-item parser errors skip upstream-deletion marking
- refreshes are serialized (in-process lock + SQLite lease)
- `--all` honors `refresh_interval_hours` unless `--force`
- item count above 200_000 blocks ingest (no silent truncation)

Ylang starts fully offline. A failed refresh does not block the library,
improver, or gateway. Last successful revision is preserved.

## Static triage

Candidates get `risk_level` (`low` / `review` / `high`) plus `risk_reasons[]`.
There is **no** `SAFE = true`. Quality scoring is explainable and cheap (no
LLM required to import). Task families are stable (`code`, `debugging`, …);
model names are hints, not categories.

Rejected content hashes are remembered so the same unchanged prompt does not
reappear as new.

## Outcome attribution

`ylang prompts metrics` `promoted_improved` / `promoted_regressed` /
`promoted_pending_outcome` are **observational** and require:

- exact promoted template id and version
- usage after the promote baseline `captured_at`
- enough versioned injections (`MIN_OUTCOME_SAMPLES = 3`)

New improver events record `id@version` in `improver_context_templates`.
Legacy bare ids stay unknown and are **not** attached to a newly promoted V2.
All-time V1 usage is not mixed into V2. Small samples, missing outcomes, and
confounders (`unversioned_events`, `other_template_versions`) remain visible.
These trends are not controlled comparative evidence.

A working evaluation runner does **not** prove a prompt is better. See
[evaluation methodology](evaluation-methodology.md).

## Source layout drift

A successful GitHub tree fetch that matches **zero** adapter files is a refresh
**error** and marks the source **incompatible** (and disables it). Copilot
would accept `prompts/*.prompt.md` and `.github/prompts/*.prompt.md` **if they
exist**; as of 2026-09-13 they do not. Fabric matches `data/patterns/*/system.md`
and any `**/patterns/*/system.md`. Live layout contracts stay opt-in:
`YLANG_NETWORK_TESTS=1 pytest -m network`.

## Permissions and failure states

| Action | Permission | Failure |
|--------|------------|---------|
| `sources enable` incompatible id | refused | `SourcePolicyError` / CLI exit 1 |
| scheduled `--all` before interval | skip | status `skipped` |
| refresh in progress | blocked | lease / lock |
| missing license policy | blocked | last-known-good kept |
| `evaluate` inspect | always | zero paid calls |
| `evaluate --mode execute` without `--authorize-paid` | refused | exit 1, no Engine call |
| execute budget `<= 0` (non-simulated) | refused | exit 1 |
| execute without `--fixture-file` | refused | exit 1 |
| promote high-risk | `--acknowledge-risk` | `PromotionError` |

## Rollback / recovery

- Failed refresh: `last_revision` / candidate bodies unchanged; `last_error` set
- Steal expired refresh lease after 600s
- Disable a source: `ylang prompts sources disable <id>`
- Reject a bad promote by saving a new template version (immutable history)
- SQLite backup: `ylang backup` (see [deployment.md](deployment.md))

## Non-goals

Ylang does not add a vector database, cloud evaluation SaaS, more public
sources, or a prompt marketplace. Dedup is exact hash plus normalized
fingerprint.

## Optional local schedule

Default remains off. After enabling **eligible** sources:

```bash
sudo cp deploy/ylang-prompts-refresh.service deploy/ylang-prompts-refresh.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ylang-prompts-refresh.timer
```

Or cron:

```bash
0 6 * * 1 sg ylang -c 'set -a && source /srv/ylang/ylang.env && set +a && ylang prompts refresh --all'
```

`--all` skips sources whose interval has not elapsed. Use `--force` only for
an operator-initiated catch-up.

Recommended: daily for prompts.chat; weekly for Fabric. Do not enable
`github-awesome-copilot` until live layout again contains v1 prompt files.

## MCP

`import_public_prompts` writes **candidates**. Omit `url` to refresh
prompts.chat. An arbitrary URL is a one-shot CSV import, not a scheduled
source. MCP does not run paid execute evaluation.

## Tests

Default CI uses fixtures only (`pytest -m "not llm_e2e and not network"`).
Optional live contracts: `YLANG_NETWORK_TESTS=1 pytest -m network`.
A simulated provider proves mechanics, not real prompt quality.
