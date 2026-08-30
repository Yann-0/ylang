# Y4 / Y5 — Agent Observability and Operator Console

## Y4 — Agent / tool observability

### Stance

**MCP is infrastructure, not the product moat.** The moat is control-plane answers over observable actions.

### Observable chain (where technically visible)

```text
AGENT / CLIENT
  → MCP SERVER (ylang) and/or GATEWAY
    → TOOL (mcp_tool / OpenAI tools)
      → MODEL (Engine → LiteLLM)
        → RESULT (usage / trace)
          → FOLLOW-UP (parent_trace_id children)
```

### What to record

| Observable | How |
|------------|-----|
| Client surface | `surface` |
| MCP tool name | `mcp_tool` on trace |
| Gateway virtual route | `selected_route` (`route-code`, …) |
| Tool calls returned by model | `tool_calls_json` (names/ids only by default) |
| Parent/child | `trace_id` / `parent_trace_id` |
| Result | `result_status`, tokens, cost, latency |

### What Ylang must **not** pretend to know

- Hidden agent reasoning / chain-of-thought inside Cursor or other hosts  
- Tools the agent called without going through Ylang  
- Whether the human “liked” the answer without a USER SIGNAL  
- Cross-process causality without an explicit parent id header/param  

Document these limits in console Trace detail (“Not observed”).

### Support matrix

| Path | Parent/child | Notes |
|------|--------------|-------|
| MCP `improve_prompt` | Single trace | `mcp_tool` set |
| Gateway chat | One trace per completion | Stream: one usage row at end (already) |
| Gateway tool round-trip | Child traces if Engine invoked again | Wire when gateway loops tools |
| Cursor hooks | `session_id` / `workspace` / `parent_trace_id` via improve hook | Fail-open hooks stay |

---

## Y5 — Operator console

### Target information architecture

Reorganize around **operator questions**, not internal package names.

#### TODAY

Answers: What is happening right now / last 24h?

- Request count  
- Spend (vs budget)  
- Success / failure counts  
- p50 / p95 latency  
- Local vs cloud model split  

#### QUALITY

Answers: Are outcomes getting better or worse?

- Outcome / eval trends by signal class  
- Problematic workflows (activity / mcp_tool)  
- Templates losing effectiveness  

#### ROUTING

Answers: Is policy behaving as intended? Where is money wasted?

- Model distribution  
- Fallback rate / cooldown hits  
- Provider failures  
- Avoidable cloud cost (budget bypass attempts, expensive ties)  

#### PROPOSALS

Answers: What should I change, and why?

- Measurable suggestions  
- Evidence + estimated impact  
- Apply / Reject (existing governed flow)  

#### PRIVACY

Answers: What are we storing?

- Capture-level policy  
- Retention  
- Sensitive-trace count (heuristic)  
- Link to export/backup/purge  

### Anti-patterns

- Vanity metrics with no decision attached  
- Charts that only restate module health  
- Cards in hero/overview that don’t answer the five homes above  
- Duplicating Optimizer wording without evidence  

### Migration from current console

Current overview is **improver-funnel + health + budget** oriented (`page_modules/overview.py`). Keep those signals but **relabel and regroup** under TODAY / QUALITY; move deep template studio / facts / settings to secondary nav.

Do not rewrite all HTML at once: introduce hub routes + queries first (`YLANG-CP-050`…), then retire redundant panels.

### Data honesty

Every chart must derive from real SQLite aggregates (usage / feedback / proposals). No placeholder random series. Gate in [07_QA_GATES.md](07_QA_GATES.md).
