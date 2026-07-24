# Quality improvement loop

Recursive maintainability / docs / CI passes over `src/ylang/`. Each wave appends metrics and notes. Stop when soft limits are mostly met or remaining debt is low-ROI / high-regression-risk.

See [quality-charter.md](quality-charter.md) for principles and soft limits.

## Wave 0 — Baseline (before edits)

Captured 2026-07-20 against `ylang` v0.5.2.

| Metric | Value |
|--------|-------|
| Top files (LOC) | `pages.py` 2106, `improver.py` 1512, `routes.py` 1418, `mcp/tools.py` 654, `proposals.py` 601, `optimizer.py` 556, `library/store.py` 549, `engine.py` 534 |
| Functions ≥80 LOC | 22 |
| Longest function | `register_console_routes` — **1156 LOC** (`console/routes.py`) |
| pyright/mypy in CI | No (ruff + pytest only) |
| `_parse_model_list` copies | 2 duplicate implementations |
| Embedded static in `pages.py` | ~16.7k chars in `<style>`/`<script>` (~88k file) |
| Tests (`not llm_e2e`) | 433 collected |

## Wave 1 — Console + domain + config + CI

**Changes**

- Console: `ConsoleContext`; `route_modules/*`; `page_modules/*`; static CSS/JS extract + cache headers; lazy imports to break `console`↔`mcp` cycles
- Improver: `improve` → `_run_improve_completion` / `_process_improve_completion` / salvage helpers; typed parse errors with fail-open fallback
- Optimizer: suggestion families as helpers; narrowed settings `except`
- MCP: `serializers.py`; registration stays thin
- Config: `core/config_parsers.py`; `get_effective_settings`; authority docs
- CI: pyright (non-blocking) + pinned `litellm`/`pydantic`; docs charter/loop/architecture/console/development

**After Wave 1 (approx.)**

| Metric | Value |
|--------|-------|
| `routes.py` / `pages.py` / `tools.py` | 54 / 45 / ~435 (serializers split) |
| Longest function | `register_tools` ~387 LOC (then addressed in Wave 2) |
| Functions ≥80 | ~27 (more medium registrars; no 1k+ god-function) |
| Config parsers | Single shared `parse_model_list` |
| Tests | **433 passed** |

## Wave 2 — MCP tool groups (focused)

**Changes**

- Split `register_tools` into `mcp/tool_groups/{core_improve,library,memory_usage,analytics}.py`
- Facade `mcp/tools.py` (~19 LOC) orchestrates groups

**After Wave 2 (final)**

| Metric | Before (W0) | After (W2) |
|--------|-------------|------------|
| Largest console monoliths | pages 2106, routes 1418 | pages facade **45**, routes **54** (+ modular packages) |
| Longest function | 1156 (`register_console_routes`) | **328** (`render_settings_page`) |
| `Improver.improve` | 229 LOC | **67 LOC** |
| `mcp/tools.py` | 654 | **19** (+ serializers + tool_groups) |
| `_parse_model_list` impls | 2 copies | **1** shared (`config_parsers`) + thin wrappers |
| pyright in CI | No | **Yes** (continue-on-error) |
| Dep pins | unpinned litellm/pydantic | `litellm>=1.40,<2`, `pydantic>=2.6,<3` |
| Functions ≥80 | 22 | 29 (more modular mid-size; no god-function) |
| Tests | 433 collected | **433 passed**, ruff clean |

### Residual debt (post–Wave 2; superseded by Wave 3)

| Item | Why left (W2) |
|------|----------------|
| `improver/improver.py` ~1623 LOC | Mostly pure validation/salvage helpers |
| HTML renderers 170–328 LOC | Server-rendered screens |
| `proposals.py` / `optimizer.py` / `store.py` ~550–600 | Near soft file limit |
| pyright ~194 basic-mode errors | Mostly sqlite row typing |
| LLM `except Exception` in engine/router | Required for provider fallback |

---

## Wave 3 — Improver modules + pyright root causes

**Changes**

- Extracted `improver/parse.py`, `validate.py`, `salvage.py`; `improver.py` keeps `Improver` + cache/orchestration (~784 LOC); re-exports for tests
- Added `core/sqlite_rows.py` (`SqliteRow`, `cell_*`); wired into `usage/store.py`, `feedback.py`, `core/memory.py`
- Typed `_ModeBucket` / `FeedbackEvent` in `improver_analytics.py`
- Pyright `venvPath` / `venv` so site-packages resolve
- Context tests: set `YLANG_IMPROVER_TIMEOUT_SEC=25` so fast-path does not zero `learned_template_limit`

**Metrics**

| Metric | Post–Wave 2 | Post–Wave 3 | Original (W0) |
|--------|-------------|-------------|----------------|
| `improver/improver.py` LOC | ~1623 | **784** (+ parse 148, validate 465, salvage 337) | 1512 (monolith) |
| Longest function | 328 (`render_settings_page`) | **328** (unchanged) | 1156 |
| Top pyright file | `usage/store.py` ~96 | store **off the list** | n/a |
| Pyright errors | ~194–198 | **56** | n/a (not in CI) |
| Tests | 433 passed | **433 passed** | 433 collected |
| Ruff | clean | **clean** | — |

### Remaining pyright categories (keep CI `continue-on-error`)

| Category | Approx. | Notes |
|----------|---------|--------|
| Form/`UploadFile` → `int`/`float` | ~6 | Console multipart form coercion |
| `settings.py` Activity dict typing | ~14 | Model-list load typing |
| LiteLLM exception exports | ~4 | Stub gaps |
| `object` attr / iterable | ~9 | Library search / mixed summaries |
| Misc (engine, context, gateway) | ~20 | Gradual cleanup |

### Residual debt (stop)

| Item | Why left |
|------|----------|
| HTML renderers 170–328 LOC | Inherent markup; low ROI to split further |
| `proposals` / `optimizer` / `store` ~550–600 | Domain-coherent near soft limit |
| pyright 56 errors | Categorized; not near-zero enough to make CI blocking |
| LLM `except Exception` | Required fail-open / fallback |

**Stop rationale (Wave 4 not justified):** Improver concentration split into focused modules; pyright cut ~70% with shared row helpers + venv; orchestration soft limits already met since Wave 2; further work is incremental typing/HTML churn without user impact.
