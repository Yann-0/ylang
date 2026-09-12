# Ylang — Public Prompt Source Policy

**Date:** 2026-09-12  
**Companion:** `docs/strategy/YLANG_PROMPT_INTELLIGENCE_20260912.md`

This document defines which public prompt sources Ylang may refresh automatically and how imported content must be governed.

The core principle is:

> **Refresh automatically; trust manually.**

Internet prompt content is untrusted until reviewed/evaluated.

---

# 1. Source tiers

## Tier A — scheduled-refresh eligible

Tier-A sources must have:

- a stable canonical location;
- explicit reusable licensing compatible with Ylang's use;
- a parser/adapter with tests;
- clear upstream item identity;
- provenance that can be persisted;
- no requirement to execute remote code.

Initial Tier-A allowlist:

### `prompts-chat`

Canonical repo: `https://github.com/f/prompts.chat`

Eligible content:

- `prompts.csv` / equivalent structured prompt data.

License policy:

- repository license states prompt content/data is CC0 1.0.

Use:

- broad generic prompt candidate source.

Trust:

- `community-broad`.

Default refresh:

- daily or weekly conditional fetch.

### `github-awesome-copilot`

Canonical repo: `https://github.com/github/awesome-copilot`

Eligible content for v1:

- `.github/prompts`-style / repository prompt files;
- prompt-specific metadata/frontmatter.

Not eligible for automatic conversion in v1:

- arbitrary agents;
- skills;
- MCP server definitions;
- instructions that imply tool permissions.

License:

- MIT.

Use:

- contemporary software-development/agent prompt candidates.

Trust:

- `curated-coding`.

Default refresh:

- daily/weekly Git revision check.

### `fabric-patterns`

Canonical repo: `https://github.com/danielmiessler/Fabric`

Eligible content:

- reusable pattern prompt text under the canonical patterns area.

License:

- MIT.

Use:

- structured analysis/extraction/research candidate prompts.

Trust:

- `curated-patterns`.

Default refresh:

- weekly Git revision check.

---

# 2. Tier B — reference only by default

These sources may influence quality rules, adapters or manual imports but should not be wholesale scheduled-ingestion sources in the first implementation.

## DAIR.AI Prompt Engineering Guide

- Repo: `https://github.com/dair-ai/Prompt-Engineering-Guide`
- License: MIT.
- Role: current prompting techniques/examples/research references.
- Reason not Tier A: repository is primarily educational prose rather than a clean prompt catalog.

## OpenAI Cookbook

- Repo: `https://github.com/openai/openai-cookbook`
- License: MIT.
- Role: model/API/prompt technique examples.
- Reason not Tier A: examples are embedded in notebooks/articles/code and are often API/model specific.

## Microsoft Promptbase

- Repo: `https://github.com/microsoft/promptbase`
- License: MIT.
- Role: prompt strategy/research examples.
- Reason not Tier A initially: small/research-oriented collection; value is technique rather than bulk library volume.

Provider docs (OpenAI/Anthropic/etc.) are **guidance sources**, not automatic prompt-copy sources, unless a specific content set has explicit compatible licensing and an approved adapter.

---

# 3. Source registry requirements

Each scheduled source record must include:

- immutable `source_id`;
- human name;
- canonical URL;
- repository URL when relevant;
- adapter name/version;
- license identifier/text reference;
- trust tier;
- enabled flag;
- refresh interval;
- last attempted refresh;
- last successful refresh;
- last revision/commit/etag;
- last error;
- policy version.

Source configuration should be local and auditable.

Do not use a remotely mutable source registry to decide what Ylang trusts.

---

# 4. Network policy

Scheduled refresh may contact only explicitly approved source hosts/URLs/adapters.

Manual one-off import of an arbitrary URL may remain supported for operator use, but it must not silently register that URL as a scheduled trusted source.

For scheduled refresh:

- follow only limited redirects;
- reject unexpected scheme changes;
- use HTTPS;
- bound response size;
- bound timeout;
- validate expected content format;
- record final source URL/revision;
- do not execute downloaded code/scripts;
- do not render remote HTML/JS to obtain prompts in v1.

Prefer Git/raw/static data over scraping websites.

---

# 5. Candidate lifecycle

Every new upstream item starts as a candidate.

Allowed states:

```text
candidate_new
candidate_changed
reviewed
promoted
rejected
removed_upstream
quarantined
```

An upstream update to a previously promoted item creates a **new changed candidate**. It does not replace the active Ylang template.

A rejected prompt remains known by hash/revision to avoid repeatedly presenting the same rejected content as new.

If upstream removes a prompt, preserve local history and mark the source item removed.

---

# 6. Provenance requirements

For every candidate persist, where available:

- source ID;
- upstream item ID/path;
- canonical upstream URL;
- repository revision / commit SHA or ETag;
- fetched timestamp;
- content SHA-256;
- normalized content fingerprint;
- upstream title/name;
- upstream metadata/frontmatter;
- license source;
- adapter version.

A promoted template version must retain a durable link to the exact candidate/source revision it came from.

---

# 7. License policy

The importer must never infer “public on GitHub = free to reuse”.

Scheduled ingestion requires an approved source-level license policy.

Persist at least:

- SPDX identifier when available;
- source license URL/path;
- license policy decision date/version.

If source licensing changes or becomes ambiguous:

- stop scheduled promotion/import of new content;
- preserve existing historical provenance;
- flag source for human review.

Do not silently delete previously promoted local templates solely because upstream licensing metadata changed; record the issue for owner/legal review.

---

# 8. Static risk checks

Before review/promotion, flag candidates containing suspicious instructions such as:

- reveal API keys, environment variables or secrets;
- upload/exfiltrate private files;
- disable safety or ignore system/developer instructions;
- run destructive commands;
- install/execute untrusted code;
- alter Git history destructively;
- send external messages/perform transactions without confirmation;
- request broad tool permissions unrelated to task purpose;
- conceal instructions via encoding/obfuscation.

These checks should produce reason codes, not a magical “safe” boolean.

Possible result model:

```text
risk_level: low | review | high
risk_reasons: [...]
```

High-risk candidates should default to quarantined/rejected until explicitly reviewed.

---

# 9. Quality checks

Static quality checks should be explainable and cheap.

Possible dimensions:

- clear task objective;
- declared inputs;
- explicit output expectation;
- usable variables/placeholders;
- excessive persona fluff;
- excessive length;
- contradictory instructions;
- likely model-version staleness;
- tool assumptions;
- duplicated content;
- overly generic “act as...” pattern;
- source freshness.

Static scoring is triage only.

Measured runtime outcomes outrank static score.

---

# 10. Refresh behavior

Refresh must be idempotent.

If source revision and item hashes are unchanged:

- create no new candidate versions;
- update last-success metadata only.

If source changed:

- parse changed/new items;
- identify removed items;
- run candidate normalization/safety/dedup;
- create candidates only for meaningful changes.

Generate a refresh summary:

```text
source
revision_before
revision_after
new
changed
removed
duplicates
quarantined
errors
```

Keep the summary locally.

---

# 11. Scheduling

Automatic refresh is opt-in/off by default for existing installations unless the migration policy explicitly decides otherwise.

Recommended default after enablement:

- no more than daily for actively changing sources;
- weekly is acceptable for Fabric/reference-style sources.

Use local scheduling mechanisms consistent with Ylang's deployment style:

- CLI + cron/systemd timer;
- existing local scheduling abstraction if one already exists.

Do not add a cloud scheduler.

---

# 12. Promotion policy

Promotion must be explicit.

Promotion should show:

- source and license;
- upstream revision;
- prompt diff/content;
- duplicate/related local templates;
- risk flags;
- quality/task metadata;
- any evaluation result.

Promotion creates an immutable local template version and never overwrites a user-authored template without an explicit versioning decision.

---

# 13. Tests required

At minimum test:

- unchanged source refresh is idempotent;
- upstream changed item creates candidate change, not active overwrite;
- removed upstream item keeps local provenance/history;
- duplicate across two sources is detected;
- source with invalid/missing license policy is blocked;
- unexpected redirect/host/scheme is blocked for scheduled refresh;
- oversized response is rejected;
- malformed source does not corrupt library;
- suspicious candidate gets risk flags;
- candidate cannot auto-promote;
- promotion preserves provenance;
- existing Ylang DB upgrades safely;
- offline Ylang startup works with source refresh unavailable.

---

# 14. External references used to define this policy

- prompts.chat license (prompt data CC0): https://github.com/f/prompts.chat/blob/main/LICENSE
- GitHub awesome-copilot license (MIT): https://github.com/github/awesome-copilot/blob/main/LICENSE
- GitHub prompt-file guidance: https://github.com/github/awesome-copilot/blob/main/instructions/prompt.instructions.md
- Fabric patterns: https://github.com/danielmiessler/Fabric
- Fabric license: https://github.com/danielmiessler/Fabric/blob/main/LICENSE
- DAIR.AI Prompt Engineering Guide: https://github.com/dair-ai/Prompt-Engineering-Guide
- OpenAI Cookbook: https://github.com/openai/openai-cookbook
- Microsoft Promptbase: https://github.com/microsoft/promptbase
- Langfuse prompt management concepts: https://langfuse.com/docs/prompt-management/overview

This source list is deliberately small. Excellence comes from evaluation and curation, not from importing the largest number of prompts.
