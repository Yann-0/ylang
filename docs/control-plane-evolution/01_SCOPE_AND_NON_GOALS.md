# Y0 — Scope and Non-Goals

**Program:** Evolve Ylang into a local-first AI Control Plane  
**Companion:** [00_CURRENT_REALITY.md](00_CURRENT_REALITY.md)

## Mission

Make AI usage through Ylang **observable, explainable, evaluable, and governable** — without abandoning the existing Engine / usage / proposals stack.

Ylang must answer:

| Question | Control-plane concern |
|----------|----------------------|
| What happened? | Trace |
| Which context / prompt / tools were involved? | Context + tool graph |
| Which model / provider was selected? | Route |
| Why was that route selected? | Policy explanation |
| How much did it cost? | Economics |
| How long did it take? | Latency |
| Did it succeed? | Result status |
| Was the result useful? | Evaluation |
| Could another route / template perform better? | Experiment + proposals |
| What change is proposed, and what evidence supports it? | Governed apply |

## In scope

1. **Canonical trace model** extending the existing SQLite `usage` (and related) schema — not a parallel telemetry product.
2. **Explainable deterministic routing** built on current ModelRouter seams; persist reasons without leaking secrets.
3. **Evaluation taxonomy** over existing outcomes, feedback, proxies, and heuristics.
4. **Experiments** comparing templates, routes, models, cost, latency, quality — still **PROPOSE → REVIEW → APPLY**.
5. **Agent/tool observability** for what faces can actually see (MCP tool name, gateway tools, parent/child where available).
6. **Operator console** reorganized around Today / Quality / Routing / Proposals / Privacy.
7. **Local-first hardening**: bind/auth/cookies/WAL/backup/tokens/logs/rate limits; no accidental public gateway.
8. **QA gates + run log** with reproducible evidence.

## Non-goals (explicit)

| Non-goal | Why |
|----------|-----|
| Another MCP server / MCP-first rewrite | MCP is one face; the product is the control plane |
| Ylang-operated cloud storage | Trust boundary: local/private/LAN-first |
| Public internet gateway by default | History: exposure attempts reverted in `d3061d9` |
| Blind persistence of raw prompts/context | Privacy requirement — capture must be configurable + redacted |
| Sophisticated ML router as first step | Prefer deterministic policy + measured outcomes |
| Automatic self-modifying production router | Optimization remains propose → apply |
| Claiming agent “hidden reasoning” | Record only observable actions and triggers |
| Vanity dashboards | Every chart must answer an operator question |
| Greenfield telemetry DB unrelated to usage | Build on `usage` / migrations |
| Breaking old SQLite databases | Additive migrations only |
| Replacing LiteLLM / inventing a new provider SDK | Keep Engine → LiteLLM path |

## Trust boundary

**Default:** Ylang stays local / private / LAN-first.

- External provider calls configured by the operator are allowed.
- Ylang-operated cloud storage is **out of scope**.
- Do not make the gateway publicly reachable by default.
- Revisit public exposure only with **strong new evidence + explicit owner approval**.

## Delivery posture

- Smallest change that advances a named task (`YLANG-CP-NNN`).
- Docs first for waves that define models; then migrations + Engine persistence; then console; then gates.
- Do not delete `routes.py.new` until cleanup task proves safe ([00_CURRENT_REALITY.md](00_CURRENT_REALITY.md)).

## Success definition (program-level)

Ylang is **not** finished because MCP connects.

It is finished for this program when hard exit gates in [07_QA_GATES.md](07_QA_GATES.md) pass with evidence recorded in [08_RUN_LOG.md](08_RUN_LOG.md).
