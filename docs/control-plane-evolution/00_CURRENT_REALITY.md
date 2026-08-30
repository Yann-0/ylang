# Y0 — Current Reality

**Audit date:** 2026-08-30  
**Repository root:** `/srv/ylang/app` (workspace wrapper: `/srv/ylang`)  
**Package version:** `0.5.2` (`pyproject.toml`)

## Git snapshot

| Field | Value |
|-------|-------|
| HEAD | `5027e7505ca5529cf1c9f9391cf09f6f5b9bb314` |
| Branch | `main` tracking `origin/main` |
| Status | Clean tree except untracked `.cursor/ylang-improved-prompt.md` |
| HEAD subject | `chore(console): keep routes.py.new alongside modular console routes` |

### Trust-boundary history (gateway exposure)

Recent commits show a deliberate public-HTTPS experiment for Cursor cloud, then an explicit revert:

| Commit | Meaning |
|--------|---------|
| `8847d9b`…`c25aaa9` | Publish / path-proxy public Cursor endpoint |
| **`d3061d9`** | **`revert(gateway): keep Ylang off the public internet`** — dropped Apache vhost/path-proxy helpers; documented private/LAN-first stance |

**Strategic default today:** local/private/LAN-first. Do not re-expose the gateway publicly without owner approval and strong new evidence.

Default HTTP bind remains `YLANG_HOST=0.0.0.0` (LAN-reachable). That is **not** the same as public internet exposure; public reachability requires operator reverse-proxy/DNS choices that were reverted.

---

## Product identity (as shipped)

Ylang is **not** “an MCP server with extras.” It is already a **local-first AI efficiency / control stack** with three HTTP faces plus CLI:

1. **MCP** — stdio or HTTP `/mcp` (17 tools)
2. **OpenAI-compatible gateway** — `/v1/chat/completions`, `/v1/models`, `/usage`, `/health`
3. **Admin console** — `/console/*`
4. **CLI** — `usage`, `patterns`, `backup`, `export`, `import`, `doctor`, `init`

Architecture principle (live in code): **one Engine, multiple thin faces**. Faces must not call LiteLLM directly.

---

## Capability audit (code vs README labels)

| Capability | Status | Evidence |
|------------|--------|----------|
| Engine (`complete` / `complete_stream`) | **Live** | `core/engine.py` — only LiteLLM call sites; fallback chain; usage write |
| ModelRouter | **Live** | Activity lists, preference reorder, budget filter, cooldown, quality-band cost tie-break, fallback floor |
| LiteLLM | **Live** | Sync `litellm.completion` in engine (stream + non-stream) |
| MCP tools (17) | **Live** | `mcp/server.py` `_TOOL_NAMES` |
| Gateway | **Live** on HTTP | `gateway/routes.py`; virtual `route-*` models |
| Console | **Live** | Modular `route_modules/` + `page_modules/` |
| Usage store | **Live** | SQLite `usage` table; write on every Engine call |
| Outcomes / improver metadata | **Partial** | Columns: validated, changed, rejection_reason, task_class, accepted, context templates |
| Edit feedback | **Live** | `feedback_events` + `record_prompt_edit` + dual env/runtime gate |
| Experiments | **Live** | `prompt_experiments`; improver variant resolution; console + MCP |
| Optimizer | **Live** | Propose-only suggestions; kinds include runtime_setting / learned_template / archive |
| Patterns | **Live** | Detectors + learned templates + CLI `patterns` |
| Proposals / apply | **Live** | Governed Apply via `console/proposals.py` + `apply_audit_log` |
| Runtime settings | **Live** | SQLite overrides + hot-reload merge |
| Budget | **Live** | Rolling 24h cost; drop cloud candidates when over cap |
| Template effectiveness | **Live** | Accept-rate scoring; retrieval blocking for zero-accept |
| Facts / memory | **Live** | Scoped facts; workspace column (migration 1) |
| Migrations | **Live** | Versions 1–10 in `core/migrations.py` |
| Auth | **Live** | Bearer + HttpOnly session cookie; `/health` + login/static public |
| Rate limit | **Live** | Optional per-IP middleware |
| CLI ops | **Live** | backup / export / import / doctor |
| CI | **Live** | Ruff + pytest (`not llm_e2e`); pyright continue-on-error |
| Canonical **trace ID / routing reason / parent-child** | **Live** | Migration v11 + Engine write path |
| Operator “Today / Quality / Routing / Privacy” home | **Live** | `/console/today`, `/quality`, `/routing`, `/privacy` |
| Public cloud storage by Ylang | **Absent (intentional)** | Local SQLite only |

### MCP tools (exact list)

`improve_prompt`, `save_template`, `recall_template`, `list_templates`, `import_public_prompts`, `remember`, `recall_facts`, `recall_usage`, `usage_summary`, `detect_patterns`, `save_learned_template`, `search_templates`, `improver_analytics`, `template_effectiveness_report`, `optimization_suggestions`, `record_prompt_edit`, `create_experiment_variant`

---

## Data model today

**Single SQLite DB** (default `~/.ylang/ylang.db`), WAL + busy_timeout, shared connection via `open_stores()`.

| Table | Role |
|-------|------|
| `usage` | Per-completion metrics + improver outcome columns |
| `templates` / `template_versions` | Versioned prompt library |
| `templates_fts` | FTS5 search |
| `facts` | Scoped memory (+ workspace) |
| `feedback_events` | Edit-distance / prompt_edit signals |
| `prompt_experiments` | A/B variant config |
| `runtime_settings` | Console-editable overrides |
| `improver_cache` | Short TTL result cache |
| `apply_audit_log` | Governed apply history |
| `schema_migrations` | Version ledger |

**What usage does *not* store today:** trace_id, parent_trace_id, routing_reason, candidate list, fallback events, tool-call graph, prompt hash (beyond truncated improver sample), policy decision, evaluation score, retention/redaction metadata.

---

## Console modularization

Canonical registration path:

```
console/routes.py
  → ConsoleContext
  → route_modules/* (HTTP handlers)
  → page_modules/* (HTML)
```

`routes.py` is a thin orchestrator (~54 lines). Domain handlers live under `route_modules/`; screens under `page_modules/`.

### `routes.py.new`

**Removed** in YLANG-CP-080 after confirming no runtime imports (was byte-identical to `routes.py`).


---

## Routing reality

`ModelRouter` already applies, in order:

1. Activity → configured candidate list  
2. Usage-based preference reorder (except `improve` bucket)  
3. Daily budget filter (strip cloud when over cap)  
4. Availability (provider key + cooldown)  
5. Quality-band + estimated unit cost tie-break  
6. Explicit model override prepended into attempt chain  
7. Local fallback floor always appended  

`format_routing_report()` explains selection at **startup** to stderr. **Per-request routing reasons are persisted** on usage rows as `routing_reason_json`.

---

## Evaluation / optimization reality

| Signal | Where | Auto-applies? |
|--------|-------|---------------|
| `improver_accepted` / validated / changed | `usage` | No |
| Edit distance (`prompt_edit`) | `feedback_events` | No |
| Template effectiveness | Analytics + retrieval block | Retrieval may exclude zero-accept templates |
| Optimization suggestions | Optimizer + console proposals | **Propose → Apply only** |
| Experiment winners | Proposals | **Propose → Apply only** |

No automatic self-modifying production router was found.

---

## Transport & security posture (summary)

| Topic | Current |
|-------|---------|
| Default host | `0.0.0.0` (LAN bind) |
| Public internet gateway | **Reverted / not shipped** |
| Auth | Bearer required for HTTP faces except `/health`, login, static |
| Cookie | HttpOnly, SameSite=lax, `secure=False` for plain HTTP LAN |
| CSRF | No dedicated CSRF token; SameSite=lax mitigates some cross-site POST |
| Secrets | Provider keys via env; never in usage rows |
| Logs | Fallback warnings may include error strings — review for secret leakage |
| Backup | `ylang backup` online SQLite backup API |

---

## Test / CI reality (pre-control-plane gates)

| Gate | Tooling |
|------|---------|
| Lint | `ruff check .` |
| Types | `pyright` (CI continue-on-error) |
| Unit/integration | `pytest -m "not llm_e2e"` |
| Optional live LLM | `@llm_e2e` with Ollama |

Hard control-plane exit gates (trace correctness, reproducible routing reason, privacy defaults, etc.) are **defined in `07_QA_GATES.md`** and largely **not yet implemented** — see `08_RUN_LOG.md`.

---

## Verdict

Ylang already owns the hard parts of a **local AI control plane**: single completion path, usage economics, improver outcomes, governed proposals, experiments, and a browser operator surface. The evolution work is **observability + explainability + evaluation coherence**, not greenfield MCP.

Primary gaps vs target:

1. Canonical **trace** model (extend `usage`, don’t invent a parallel telemetry DB)  
2. **Persisted routing explanations** (without secrets)  
3. Explicit **signal taxonomy** for evaluation  
4. **Parent/child** tool/agent observability where faces can see it  
5. Console reorganized around **operator questions**  
6. Hardened **local-first** defaults and privacy capture policy
