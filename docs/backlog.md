# Ylang — Open backlog

**Updated:** 2026-07-05 (v0.3.0)  
**Status:** Active — items not yet shipped

Completed work: [backlog-shipped.md](./backlog-shipped.md).

---

## Remaining (post v0.3.0)

| ID | Priority | Title |
|----|----------|-------|
| BL-001 | High | Mode-aware optimization layer (beyond `_MODE_GUIDANCE`) |
| BL-004 | Medium | Hook respects `auto_apply_default` for precision tools |
| BL-005 | Medium | Pattern threshold notifications |
| BL-006 | Medium | First-run setup wizard |
| BL-007 | Low | Auth token rotation grace period |
| BL-002 | Low | Full aiosqlite migration (defer until profiling demands) |

---

## BL-001 — Mode-aware Cursor mode optimization

**Priority:** High  
**Phase:** 6  
**Status:** Open

### User story

As a Cursor user working across different interaction modes (`plan`, `multitask`, `debug`, `ask`, `agent`), I want Ylang to automatically optimize its behavior, tooling, and context based on my active mode selection, so that each mode feels purpose-built without manual configuration or mode-specific workarounds.

### Context

Today, `improve_prompt` resolves Cursor mode and injects mode-specific LLM guidance (`src/ylang/improver/registry.py`), routes models by mode bucket, and sets `auto_apply_default` hints. This is a good foundation but mode handling is limited to prompt shaping and routing — there is no unified optimization layer that adapts context retrieval, tool activation, resource allocation, or mode-switch lifecycle across the full Ylang stack (improver, hooks, gateway, library retrieval).

### Scope

1. **Mode-aware optimization layer** — read the active Cursor mode and apply mode-specific optimizations (context window strategy, tool activation, prompt shaping, resource allocation).
2. **`plan` mode** — structured output templates, step decomposition scaffolding; no execution side-effects enforced.
3. **`multitask` mode** — parallel task queue management, priority ordering, inter-task dependency tracking.
4. **`debug` mode** — auto-attach relevant logs, stack traces, variable inspection hints; suppress non-debug noise.
5. **Other modes** — audit remaining Cursor modes (`ask`, `agent`) and apply analogous targeted optimizations.
6. **Mode-switch handler** — on mode selection change, tear down previous mode state and initialize the new mode's optimized context without losing in-progress work.
7. **Documentation** — describe per-mode optimization behavior and selection-driven dispatch.

### Acceptance criteria

- [ ] A mode-aware optimization module/configuration exists and is driven exclusively by the active mode selection (no build-time hard-coding of active mode).
- [ ] Each canonical mode (`plan`, `multitask`, `debug`, `ask`, `agent`) has documented, testable optimization behavior beyond the current `_MODE_GUIDANCE` strings.
- [ ] Mode switching is non-destructive: unsaved or in-progress context from the previous mode is preserved or gracefully handed off.
- [ ] Existing mode public APIs and user-facing behavior are not broken beyond the explicitly listed optimizations.
- [ ] Unit tests cover each mode optimizer; mode-switch tests assert no state leakage across permutations.
- [ ] Integration test: select `plan` → produce plan output → switch to `debug` → verify debug tooling active and plan tooling inactive.
- [ ] Mode-switch overhead is negligible (< 50 ms additional latency per switch).
- [ ] Docs updated (`cursor-integration.md`, `architecture.md`, or dedicated mode doc).

### Constraints

- Phase 1 guardrails still apply: improver remains propose-only; no optimizer/provenance/team features.
- No new dependency without explicit approval.

### References

- `src/ylang/improver/registry.py` — current mode resolution and guidance
- [cursor-integration.md](./cursor-integration.md#cursor-mode-awareness)
- [architecture.md](./architecture.md#cursor-mode-resolution)

---

## BL-002 — Full aiosqlite migration

**Priority:** Low  
**Phase:** Future  
**Status:** Open

Migrate store operations to aiosqlite only if profiling shows thread offload (`anyio.to_thread.run_sync`) is insufficient under concurrent gateway load.

---

## Shipped in v0.3.0 (see backlog-shipped.md)

CI pipeline, schema migrations, `GET /health`, rate limiting, model aliases config, backup/export/import/doctor CLI, FTS5 `search_templates`, workspace facts, analysis improver tuning, JSON logging, digest apply hints.
