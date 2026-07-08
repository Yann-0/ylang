# Ylang — Open backlog

**Updated:** 2026-07-08 (v0.4.0-pao)  
**Status:** Active — items not yet shipped

Completed work: [backlog-shipped.md](./backlog-shipped.md).

---

## Remaining (post PAO module)

| ID | Priority | Title |
|----|----------|-------|
| BL-004 | Medium | Hook respects `auto_apply_default` for precision tools |
| BL-005 | Medium | Pattern threshold notifications |
| BL-006 | Medium | First-run setup wizard |
| BL-007 | Low | Auth token rotation grace period |
| BL-002 | Low | Full aiosqlite migration (defer until profiling demands) |

---

## Shipped — Prompt Usage Analytics & Optimization (PAO-001–014)

All PAO backlog items from the 2026-07-08 analysis shipped in this release:

| ID | Title |
|----|-------|
| PAO-001 | Persist improver outcome metadata on usage rows |
| PAO-002 | Surface `improver_context_templates` in recall/analytics |
| PAO-003 | Improver funnel aggregates (`improver_analytics`, `ylang usage improver-report`) |
| PAO-004 | Template effectiveness report |
| PAO-005 | Outcome-aware template retrieval |
| PAO-006 | Improver dashboard panels |
| PAO-007 | Propose-only `optimization_suggestions` |
| PAO-008 | Semantic pattern detection (`YLANG_PATTERN_DETECTOR=semantic`) |
| PAO-009 | User edit feedback capture (`YLANG_CAPTURE_EDIT_FEEDBACK=1`) |
| PAO-010 | Dynamic prompt block assembly (`block:*` template tags) |
| PAO-011 | Mode-aware optimization layer (`improver/mode_optimizer.py`) |
| PAO-012 | Prompt experiment framework (`prompt_experiments` table, `YLANG_EXPERIMENTS=1`) |
| PAO-013 | Weekly optimization digest (extended `ylang usage digest`) |
| PAO-014 | Self-critique second pass (`YLANG_IMPROVER_CRITIQUE=1`) |

See [mcp-tools.md](./mcp-tools.md) and [database-schema.md](./database-schema.md) for API and schema details.

---

## BL-001 — Mode-aware Cursor mode optimization

**Status:** Shipped as PAO-011 (`improver/mode_optimizer.py`). Remaining BL-001 acceptance items (multitask queue UI, integration e2e) may be tracked separately if needed.

---

## BL-002 — Full aiosqlite migration

**Priority:** Low  
**Phase:** Future  
**Status:** Open

Migrate store operations to aiosqlite only if profiling shows thread offload (`anyio.to_thread.run_sync`) is insufficient under concurrent gateway load.
