# Control Plane — Run Log

Exact evidence for audits and gates. Append-only; newest entry at top.

---

## 2026-08-30 — Phase B + ship

- Dedicated `evaluation_json` column (migration v12)
- Client `parent_trace_id` / `trace_id` via gateway headers + MCP `improve_prompt`
- Suite: 465+ passed (recorded after run)

---

## 2026-08-30 — Full close-out (all tasks green)

### Shipped in this pass

- Operator hubs: `/console/today`, `/quality`, `/routing`, `/privacy`
- Improver `mcp_tool=improve_prompt`; gateway `selected_route`
- Evaluation taxonomy + assembly (`usage/evaluation.py`)
- Operator metrics + routing one-liners in MCP usage serialize
- `ylang purge-traces`; doctor bind warnings; log scrub on fallback
- Deleted `routes.py.new` (CP-080)
- Gate suite: `tests/test_control_plane_complete.py`

### Commands

```text
cd /srv/ylang/app
.venv/bin/ruff check .          → All checks passed!
.venv/bin/pytest -m "not llm_e2e" -q
→ 463 passed, 1 deselected, 2 warnings in 65.89s  (exit 0)
```

### Hard gates

CP-G-01 … CP-G-12 all **Green**. Task register YLANG-CP-001…090 all **Done**.

---

## 2026-08-30 — YLANG-CP-011…023 write path

Migration v11, capture_level, Engine traces, routing reasons. Then 447 passed.

---

## 2026-08-30 — Y0 kickoff

Program docs under `docs/control-plane-evolution/`; trust boundary `d3061d9`.
