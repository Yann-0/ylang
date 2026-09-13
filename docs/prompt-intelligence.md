# Prompt intelligence

Ylang can refresh a small allowlist of **public prompt catalogs** into a local
**candidate quarantine**. Public text is untrusted until you promote it.

> Refresh automatically; trust manually.

This is not a prompt marketplace, not a Langfuse clone, and not a cloud
service. Ylang stays a local-first personal AI control plane that learns which
prompts actually help **your** workloads.

Canonical strategy:

- [Prompt intelligence evolution](strategy/YLANG_PROMPT_INTELLIGENCE_20260912.md)
- [Public source policy](strategy/YLANG_PUBLIC_PROMPT_SOURCE_POLICY_20260912.md)

## Lifecycle

```text
source → fetch → provenance → normalize → risk scan → dedup → candidate
                                                         ↓
                              optional evaluate → human promote → template version
                                                         ↓
                              usage / outcomes / effectiveness (existing stores)
```

Internet content never becomes an active template without an explicit
`promote`. Upstream edits of a promoted prompt create `candidate_changed`;
they do not overwrite the local version. Upstream deletions mark
`removed_upstream` and keep local history.

## Allowlisted sources (Tier A)

| Source id | License | What is imported | Default cadence |
|-----------|---------|------------------|-----------------|
| `prompts-chat` | CC0 1.0 (prompt data) | structured `prompts.csv` | daily if enabled |
| `github-awesome-copilot` | MIT | `*.prompt.md` under `prompts/` or `.github/prompts/` (skips agents/skills/instructions/mcp) | daily if enabled |
| `fabric-patterns` | MIT | `system.md` under `**/patterns/` | weekly if enabled |

Scheduled refresh is **off** until you enable a source. Manual CSV/URL import
may still be used; that URL is **never** registered as a scheduled source.

Tier B references (DAIR.AI guide, OpenAI Cookbook, Promptbase, provider docs)
are not bulk-imported.

## CLI (Portal is optional)

```bash
ylang prompts sources list
ylang prompts sources enable prompts-chat
ylang prompts refresh prompts-chat
ylang prompts refresh --all          # enabled scheduled sources only
ylang prompts candidates list
ylang prompts candidates show <id>
ylang prompts candidates diff <id>
ylang prompts candidates review <id>
ylang prompts candidates reject <id>
ylang prompts candidates promote <id> [--acknowledge-risk]
ylang prompts candidates evaluate <id> [--vs TEMPLATE] [--fixture-file PATH]
ylang prompts metrics
```

`--all` never includes `manual-import`. High-risk candidates require
`--acknowledge-risk`. Promotion creates an immutable `user` template version
with provenance; upstream `tools` metadata is stored, never granted.

## Network / supply-chain

Scheduled fetch is HTTPS-only to `api.github.com` and
`raw.githubusercontent.com` on per-source URL prefixes. Redirects are bounded;
unexpected hosts, oversized payloads, HTML scraping, and remote code
execution are rejected. License text is checked against the source SPDX policy
before new items are ingested.

Ylang starts fully offline. A failed refresh does not block the library,
improver, or gateway.

## Static triage

Candidates get `risk_level` (`low` / `review` / `high`) plus `risk_reasons[]`.
There is **no** `SAFE = true`. Quality scoring is explainable and cheap (no
LLM required to import). Task families are stable (`code`, `debugging`, …);
model names are hints, not categories.

Rejected content hashes are remembered so the same unchanged prompt does not
reappear as new.

## Evaluation

`ylang prompts candidates evaluate` writes a **local comparison report**:

- current template accept rate, cost, latency, and injection count from existing usage
- candidate static risk/quality plus a body-diff ratio
- an **inactive** experiment (`traffic_pct=0`) so untrusted text is never injected into improver retrieval
- optional `--fixture-file` (operator-supplied sample only; private history is never replayed or sent to a new provider)

Promotion snapshots the current template's outcomes. Later `ylang prompts metrics` reports `promoted_improved` / `promoted_regressed` / `promoted_pending_outcome` once a template has at least three post-promotion injections. Completion-without-error is not treated as success.

The product question is not “how many prompts were imported?” It is whether
promoted prompts improved real operator work (acceptance, cost, latency).

## Source layout drift

A successful GitHub tree fetch that matches **zero** adapter files is a refresh
**error** (`source shape unexpected`), not an empty success. Copilot still
accepts `prompts/*.prompt.md` and `.github/prompts/*.prompt.md`. Fabric matches
`data/patterns/*/system.md` and any `**/patterns/*/system.md`. Live layout
contracts stay opt-in: `YLANG_NETWORK_TESTS=1 pytest -m network`.

## Non-goals

Ylang does not add a vector database or embedding index for candidate
clustering. Dedup is exact hash plus normalized fingerprint; lexical/FTS
retrieval already exists in the library. Semantic clustering stays out unless
those miss material matches on real operator data.

## Optional local schedule

Default remains off. After enabling sources:

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

Recommended: daily/weekly for prompts.chat and awesome-copilot; weekly for Fabric.

## MCP

`import_public_prompts` now writes **candidates**. Omit `url` to refresh
prompts.chat. An arbitrary URL is a one-shot CSV import, not a scheduled
source.

## Tests

Default CI uses fixtures only (`pytest -m "not llm_e2e and not network"`).
Optional live contracts: `YLANG_NETWORK_TESTS=1 pytest -m network`.
