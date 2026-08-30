# Y6 notes + Master Action Plan

## Y6 — Local-first hardening (audit findings)

| Area | Current finding | Target |
|------|-----------------|--------|
| Bearer auth | Required for HTTP faces; compare_digest | Keep; document rotation (`previous_token`) |
| Cookie/session | HttpOnly, SameSite=lax, secure=False for LAN HTTP | Documented + tested |
| HTTP bind | Default `0.0.0.0` | Doctor warns on all-interfaces bind |
| Public exposure | Apache helpers **removed** in `d3061d9` | CI asserts scripts stay gone |
| systemd | `deploy/ylang.service` | No public proxy unit |
| SQLite | WAL + busy_timeout | Keep |
| Backup/export/import | CLI ops live | + `ylang purge-traces` |
| Migrations | v1–11 | Additive trace columns |
| Tokens / provider keys | Env; not in usage | Fallback logs scrubbed |
| Console auth | Login + cookie | SameSite=lax + HttpOnly tested |
| Rate limits | Optional middleware | Keep |
| Local Ollama fallback | Default fallback model `ollama/qwen2.5` | Keep |
| Gateway accident | Health unauthenticated | OK; `/v1/*` never exempt |

---

## Task register

Status **2026-08-30** after full control-plane close-out (463 tests green).

| ID | Wave | Task | Status |
|----|------|------|--------|
| YLANG-CP-001 | Y0 | Record HEAD/status; capability audit; routes.py.new classification | **Done** |
| YLANG-CP-002 | Y0 | Write `00_CURRENT_REALITY.md` | **Done** |
| YLANG-CP-003 | Y0 | Write `01_SCOPE_AND_NON_GOALS.md` | **Done** |
| YLANG-CP-010 | Y1 | Spec canonical trace + privacy (`02_TRACE_MODEL.md`) | **Done** |
| YLANG-CP-011 | Y1 | Migration: additive usage trace columns + indexes | **Done** |
| YLANG-CP-012 | Y1 | Engine: allocate `trace_id`, persist candidates/fallback/tokens | **Done** |
| YLANG-CP-013 | Y1 | Capture-level settings (env + runtime); default `minimal` | **Done** |
| YLANG-CP-014 | Y1 | Redaction helpers + retention purge CLI | **Done** |
| YLANG-CP-015 | Y1 | Tests: historical DB upgrade; privacy defaults | **Done** |
| YLANG-CP-020 | Y2 | Spec routing reasons (`03_ROUTING_AND_POLICY.md`) | **Done** |
| YLANG-CP-021 | Y2 | `routing_reason_json` builder (no secrets) | **Done** |
| YLANG-CP-022 | Y2 | Persist reasons on every Engine write | **Done** |
| YLANG-CP-023 | Y2 | Reproducibility unit tests (frozen policy inputs) | **Done** |
| YLANG-CP-024 | Y2 | Console/API one-liner explanation | **Done** |
| YLANG-CP-030 | Y3 | Spec evaluation taxonomy (`04_EVALUATION_MODEL.md`) | **Done** |
| YLANG-CP-031 | Y3 | Classify existing metrics in code/docs helpers | **Done** |
| YLANG-CP-032 | Y3 | `evaluation_json` assembly from known signals | **Done** |
| YLANG-CP-033 | Y3 | Experiment compare dimensions (template/route/model/cost/latency) | **Done** |
| YLANG-CP-034 | Y3 | Gate: experiments never auto-apply | **Done** |
| YLANG-CP-040 | Y4 | Parent/child + mcp_tool on traces | **Done** |
| YLANG-CP-041 | Y4 | Persist safe tool_calls_json | **Done** |
| YLANG-CP-042 | Y4 | Document non-observables in console | **Done** |
| YLANG-CP-050 | Y5 | Spec operator IA (`05_OPERATOR_CONSOLE.md`) | **Done** |
| YLANG-CP-051 | Y5 | TODAY hub queries from real usage | **Done** |
| YLANG-CP-052 | Y5 | QUALITY / ROUTING / PROPOSALS / PRIVACY hubs | **Done** |
| YLANG-CP-053 | Y5 | Tests: metrics match SQLite fixtures | **Done** |
| YLANG-CP-060 | Y6 | Doctor: bind/exposure warnings | **Done** |
| YLANG-CP-061 | Y6 | Auth/cookie/CSRF review checklist + fixes | **Done** |
| YLANG-CP-062 | Y6 | Log scrub for secrets | **Done** |
| YLANG-CP-063 | Y6 | Confirm no public proxy deploy scripts return | **Done** |
| YLANG-CP-070 | QA | Integration: all completions via Engine | **Done** |
| YLANG-CP-071 | QA | Streaming + tools + fallback traced | **Done** |
| YLANG-CP-072 | QA | Budget policy + routing reason gates | **Done** |
| YLANG-CP-073 | QA | Console metrics from real data | **Done** |
| YLANG-CP-074 | QA | Private defaults remain private | **Done** |
| YLANG-CP-080 | Hygiene | Remove `routes.py.new` only after reference scan | **Done** |
| YLANG-CP-090 | Docs | Keep `08_RUN_LOG.md` updated each gate run | **Done** |

## Out of order forbidden (still)

- Public gateway without owner approval  
- Auto-apply router changes  
- Parallel telemetry DB  
