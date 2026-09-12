# Ylang — Prompt Intelligence Evolution

**Date:** 2026-09-12  
**Baseline branch:** `main`  
**Baseline SHA:** `52aa77f10abd94ed0520b6fc10b0f06e14db80c7`  
**Goal:** make Ylang excellent at discovering, curating, evaluating and learning reusable prompts without becoming a generic prompt marketplace or an unsafe auto-importer.

## Executive decision

Ylang's strongest strategic identity is:

> **A local-first personal AI control plane that learns which prompts, models and policies work best for the operator's real workloads.**

The next innovation should not be “more models” or “more dashboards”. It should be a **Prompt Intelligence Layer** that combines:

1. trusted public prompt sources;
2. controlled refresh and provenance;
3. deduplication and normalization;
4. safety and license policy;
5. task classification;
6. evaluation against real operator workloads;
7. propose → review → promote governance;
8. learning from actual outcomes.

Public prompt libraries are **candidate knowledge**, not truth. Nothing fetched from the internet should automatically become a production/default prompt.

---

# 1. Current Ylang truth

Current Ylang v0.6.0 already provides:

- local SQLite storage;
- template library with immutable versions;
- `seed`, `user`, and `learned` template origins;
- `public`, `private`, `archived` visibility;
- MCP tool `import_public_prompts`;
- CLI importer;
- current default public source: `https://raw.githubusercontent.com/f/awesome-chatgpt-prompts/main/prompts.csv`;
- FTS template search;
- prompt improver;
- usage/outcome tracking;
- learned-template proposals;
- model routing with explainable `ModelResolution`;
- cost/latency tracking;
- local-first trust boundary;
- optional metadata-only OTLP export;
- propose-only optimization/experiments.

Important current limitation:

`import_public_prompts` effectively treats a remote CSV as content to import. The current template model does not preserve rich upstream provenance such as:

- upstream repository/source ID;
- immutable source revision;
- upstream prompt ID/path;
- license;
- fetched timestamp;
- content hash;
- upstream modification detection;
- review state;
- source trust policy.

The current importer also accepts an arbitrary URL. This is useful manually, but an automatic refresh mechanism must not turn arbitrary network content into trusted executable prompt instructions.

---

# 2. Why this matters now

Prompt management is becoming a first-class infrastructure capability. Langfuse, for example, supports versioning, labels, caching, evaluation, experiments and agentic access to prompts. Ylang should not clone Langfuse. Its advantage is that it can combine prompt management with **personal/local usage outcomes and model routing**.

Recent model guidance also reinforces that prompts are increasingly model-sensitive:

- current Claude guidance differentiates prompting behavior by model generation and emphasizes clear instructions, examples and structured context;
- current OpenAI model guidance recommends separating stable prompt prefixes from dynamic context for caching and using structured outputs rather than describing schemas in prose where possible.

Therefore a “good prompt” cannot be scored only by popularity or text aesthetics. Ylang should know:

- what task it is for;
- where it came from;
- what model family assumptions it carries;
- how old it is;
- whether it performs well on the operator's actual workloads.

External design references:

- https://langfuse.com/docs/prompt-management/overview
- https://langfuse.com/docs/prompt-management/features/prompt-version-control
- https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables
- https://developers.openai.com/api/docs/guides/latest-model

---

# 3. Product principle: source → candidate → evaluate → promote

The canonical lifecycle must be:

```text
PUBLIC SOURCE
    ↓
FETCH / REFRESH
    ↓
PROVENANCE + LICENSE + HASH
    ↓
NORMALIZE
    ↓
SAFETY / QUALITY STATIC CHECKS
    ↓
DEDUP / CLUSTER
    ↓
CANDIDATE LIBRARY
    ↓
OPTIONAL EVALUATION
    ↓
HUMAN REVIEW
    ↓
PROMOTED TEMPLATE
    ↓
REAL USAGE OUTCOMES
    ↓
PROPOSE IMPROVEMENT / DEMOTION
```

Never:

```text
internet changed
→ automatically replace active prompt
```

Auto-refresh is allowed. **Auto-promotion is not.**

---

# 4. Source architecture

Do not overload the existing `TemplateSource = seed | user | learned` enum merely to encode every upstream repository.

Prefer separate source/provenance records so existing library semantics remain stable.

Suggested conceptual entities:

## `prompt_sources`

- source_id;
- name;
- source_type / adapter;
- canonical URL;
- repository URL if applicable;
- license SPDX / policy;
- refresh policy;
- enabled;
- trust tier;
- last fetch timestamp;
- last successful revision/etag;
- last error;
- created/updated timestamps.

## `prompt_source_items`

- source_id;
- upstream_item_id/path;
- upstream revision / commit SHA;
- content hash;
- raw title/name;
- normalized body hash;
- discovered timestamp;
- last seen timestamp;
- status: candidate / reviewed / promoted / rejected / removed_upstream;
- linked Ylang template ID/version if promoted;
- license metadata;
- model/task hints;
- safety flags;
- quality metadata.

The exact schema may differ if a smaller integration with existing tables is cleaner. The important requirement is that source provenance must be queryable and migration-safe.

---

# 5. Approved source strategy

Not every interesting website/repository should be auto-ingested.

Use explicit allowlisted adapters.

## Tier A — structured prompt sources, eligible for automated candidate refresh

### A1. prompts.chat / `f/prompts.chat`

- Repository: https://github.com/f/prompts.chat
- Current Ylang raw source is already derived from this lineage.
- Prompt data (`prompts.csv`, `PROMPTS.md`, user-submitted prompt text) is CC0 1.0 according to the repository license.
- This is the safest source to retain as a broad public prompt dataset.

Use a dedicated adapter instead of a generic arbitrary URL for scheduled refresh.

### A2. GitHub `awesome-copilot`

- Repository: https://github.com/github/awesome-copilot
- License: MIT.
- Contains curated `.prompt.md`, instructions, agents and skills.
- For Ylang v1 of this feature, ingest **prompt files only** as candidates; do not automatically reinterpret full agents/skills as ordinary prompts.
- Preserve frontmatter metadata when useful: description, agent, model, tools, tags.

This source is valuable for coding/agent workflows and more current than many generic “act as...” prompt lists.

### A3. Daniel Miessler `Fabric` patterns

- Repository: https://github.com/danielmiessler/Fabric
- License: MIT.
- Contains structured reusable patterns, often in Markdown/system-prompt form.
- Import patterns as candidates with source-specific adapter and tags.
- Preserve pattern path and source revision.

This is useful for analysis/research/extraction tasks, but patterns should not automatically displace local prompts.

## Tier B — reference/guidance sources, not wholesale auto-import by default

### B1. DAIR.AI Prompt Engineering Guide

- https://github.com/dair-ai/Prompt-Engineering-Guide
- MIT.
- High-quality prompting guidance and examples.
- Treat primarily as **technique/reference material**, because the repository is mostly educational prose rather than a normalized prompt catalog.
- If an adapter is later added, only import explicitly identified prompt/example blocks, never the whole prose corpus.

### B2. OpenAI Cookbook

- https://github.com/openai/openai-cookbook
- MIT.
- Valuable examples and current model-specific techniques.
- Reference/evaluation source first; do not scrape arbitrary notebook text into the prompt library.

### B3. Microsoft Promptbase

- https://github.com/microsoft/promptbase
- MIT.
- Research/examples, including prompt strategies.
- Treat as curated reference/candidate strategy source rather than bulk import unless a robust adapter is justified.

## Guidance-only sources

Official provider documentation such as Anthropic prompting docs should inform Ylang's internal prompt-quality rules and model-specific guidance, but should **not** be automatically copied wholesale into the template library unless licensing and content scope explicitly permit it.

---

# 6. Refresh model

Implement refresh as a controlled background/manual operation.

Recommended surfaces:

- CLI: `ylang prompts sources list`
- CLI: `ylang prompts refresh [source|--all]`
- CLI: `ylang prompts candidates ...`
- MCP read/propose tools only if they fit the existing API cleanly;
- optional local schedule/cron using Ylang's existing local-first operational style.

Default refresh frequency should be conservative, e.g. daily or weekly depending on source. Do not poll GitHub every few minutes.

Use conditional fetching where possible:

- ETag;
- Last-Modified;
- immutable commit SHA;
- source revision.

Record refresh result:

- unchanged;
- new items;
- changed items;
- removed upstream;
- parser failures;
- license/policy failure.

Never erase local history because upstream deleted a prompt. Mark upstream state and keep provenance.

---

# 7. Supply-chain and prompt-injection safety

Imported prompts are effectively **untrusted executable instructions**.

The refresh system must treat them similarly to third-party code/configuration.

At minimum perform static candidate checks for suspicious patterns such as:

- requests to reveal secrets/credentials;
- destructive shell commands;
- unsolicited network exfiltration;
- instructions to ignore higher-level policies;
- hidden/obfuscated instructions;
- tool-use demands inconsistent with declared prompt purpose;
- auto-execution assumptions;
- attempts to modify Ylang's own policy/configuration.

Do not pretend static scanning can guarantee safety.

The safety result should be a **flag/risk score for review**, not an automatic assertion that a prompt is safe.

Public candidates must not gain tool permissions or auto-apply behavior merely because upstream metadata asks for it.

---

# 8. Deduplication and normalization

Public prompt sources overlap heavily.

Ylang should avoid a library where 12 versions of the same generic prompt crowd search results.

Use a layered dedup strategy:

1. exact normalized content hash;
2. normalized title/name;
3. placeholder-normalized body fingerprint;
4. optional semantic similarity for candidate clustering.

Do not automatically merge semantically similar prompts that have materially different constraints.

Expose duplicate/cluster relationships for review.

Promoted local templates should not be silently overwritten by a newly fetched duplicate.

---

# 9. Task and model metadata

Candidates should be classifiable into stable task families useful to Ylang routing, for example:

- code;
- debugging;
- architecture;
- research/search;
- summarization;
- extraction;
- transformation;
- writing;
- planning;
- reasoning;
- evaluation/review;
- data analysis;
- agent/tool orchestration;
- other.

Also record provider/model assumptions when the source explicitly encodes them.

Do not hard-code current model names as the taxonomy itself.

A model-specific candidate may carry hints such as:

- model family;
- minimum capability;
- structured-output expectation;
- tool-use expectation;
- long-context expectation;
- reasoning effort guidance.

These are metadata, not absolute truth.

---

# 10. Quality scoring: popularity is not quality

Do not rank public prompts primarily by GitHub stars or source popularity.

Candidate quality should combine explainable signals such as:

- source trust tier;
- freshness;
- completeness;
- clear objective;
- explicit inputs/variables;
- explicit output contract;
- excessive verbosity penalty;
- unsafe/tool-demand flags;
- duplication penalty;
- model-specific staleness;
- real evaluation results if available;
- real Ylang usage outcomes if promoted.

Keep static quality score separate from measured runtime effectiveness.

A beautiful prompt that performs badly for the operator should lose to a simpler prompt that performs well.

---

# 11. Evaluation and promotion

Ylang already has outcomes, experiments and propose-only optimization surfaces. Reuse them.

For important task classes, allow candidate-vs-current comparison using controlled fixtures or replay-safe historical inputs where privacy permits.

Measure relevant dimensions:

- task success / explicit outcome;
- user acceptance;
- edit distance / amount of correction;
- latency;
- input/output tokens;
- cost;
- tool-call success;
- formatting/contract adherence;
- model/provider.

Do not send private historical prompts to a third-party provider solely to evaluate a public prompt unless the operator has already configured/authorized that provider and the data policy allows it.

Promotion remains:

```text
CANDIDATE
→ EVALUATED
→ PROPOSED
→ HUMAN ACCEPT
→ ACTIVE TEMPLATE VERSION
```

No automatic replacement of active prompts in this phase.

---

# 12. Retrieval innovation

Current MCP `search_templates` is FTS-oriented. Public-source growth will make retrieval quality more important.

Do not immediately add a vector database.

First improve retrieval using existing local primitives:

- FTS relevance;
- tags/task class;
- source/trust filters;
- promoted-vs-candidate state;
- freshness;
- measured effectiveness.

If semantic retrieval already exists elsewhere in Ylang, reuse it rather than duplicate it.

Only add embeddings/vector search if tests show lexical retrieval materially misses good prompts.

Local SQLite should remain the default persistence layer.

---

# 13. User experience

The Portal should answer practical questions rather than expose raw ingestion machinery.

Useful views:

## Sources

- enabled sources;
- license;
- last refresh;
- revision;
- new/changed candidate count;
- last error.

## Candidates

- prompt name;
- task class;
- source;
- changed/new;
- risk flags;
- duplicate cluster;
- static quality score;
- evaluation status;
- Review / Reject / Promote.

## Template detail

- local versions;
- upstream provenance;
- diff against upstream change;
- usage/effectiveness;
- experiment results;
- model/task metadata.

Avoid building a marketplace storefront.

---

# 14. Go-to-market discipline

Ylang is not yet proven as a standalone commercial SaaS. Do not spend months polishing prompt ingestion as an end in itself.

This feature is strategically valuable if it improves the real operator loop:

> discover better candidate → test → promote → use → measure → improve.

The first release should support **three sources maximum**:

1. prompts.chat / `f/prompts.chat`;
2. GitHub `awesome-copilot` prompt files;
3. Fabric patterns.

Everything else remains reference/future adapter work.

The goal is to ship a small but high-quality prompt intelligence system quickly and then dogfood it heavily.

---

# 15. Execution plan

## YPI-001 — Source/provenance schema

Add migration-safe storage for sources and upstream items without breaking existing template versions.

## YPI-002 — Source registry and adapters

Implement explicit adapters for the three initial Tier-A sources.

No generic scheduled arbitrary-URL refresh.

## YPI-003 — Conditional refresh

Support manual refresh plus an optional local scheduled refresh. Record source revisions and diffs.

## YPI-004 — Candidate quarantine

New/changed upstream prompts enter candidate state. They are not immediately active templates.

## YPI-005 — License/source policy

Persist source license metadata and refuse scheduled ingestion from unapproved/unlicensed sources.

## YPI-006 — Static safety/quality scan

Add explainable flags and a basic static quality rubric. Do not claim perfect safety.

## YPI-007 — Deduplication

Exact hash + normalized fingerprint. Add optional semantic clustering only if needed.

## YPI-008 — Task metadata

Classify/tag candidates using stable task families. Prefer deterministic/source metadata first; LLM assistance may propose classification but must not be required for import.

## YPI-009 — Review/promotion workflow

CLI first, Portal second if appropriate. Promotion creates a normal immutable Ylang template version with provenance link.

## YPI-010 — Evaluation bridge

Allow candidate/current prompt comparisons using existing experiment/outcome infrastructure.

## YPI-011 — Source/candidate Portal surfaces

Keep UI small and operational.

## YPI-012 — Dogfood metrics

Track:

- candidates fetched;
- duplicates removed;
- candidates promoted;
- promoted prompts actually used;
- outcome improvement vs previous template;
- cost/latency delta;
- rejected candidates and reasons.

---

# 16. Hard non-goals

Do not:

- build a public prompt marketplace;
- create Ylang cloud hosting;
- auto-promote internet prompts;
- auto-enable tools requested by public prompt metadata;
- scrape arbitrary websites on a schedule;
- ingest provider documentation wholesale;
- add a vector database by default;
- replace SQLite;
- make Langfuse a mandatory dependency;
- make external prompt sources required for Ylang to start;
- modify prompt/model policy automatically based on weak proxies;
- replace existing user/learned templates with upstream content.

---

# 17. Exit criteria

The first Prompt Intelligence release is complete when:

1. existing Ylang databases migrate safely;
2. Ylang works fully offline when refresh is disabled/unavailable;
3. three allowlisted sources can refresh idempotently;
4. every candidate has provenance, source revision/hash and license metadata;
5. upstream changes are detected without overwriting local promoted versions;
6. exact duplicates do not flood the library;
7. unsafe/suspicious candidates are flagged for review;
8. no candidate becomes active without explicit promotion;
9. promoted candidates link back to provenance;
10. candidate-vs-current evaluation can use existing experiments/outcomes;
11. CI, Ruff, Pyright, Pytest and docs are green;
12. documentation clearly explains trust boundaries and source policy.

Then stop adding sources and dogfood the system.
