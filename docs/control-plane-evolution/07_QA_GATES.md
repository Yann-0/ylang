# QA Gates — Control Plane Program

Gates are **exit criteria**. Status below reflects the close-out suite on 2026-08-30.

## Hard exit gates

| Gate ID | Requirement | Evidence type | Status |
|---------|-------------|---------------|--------|
| CP-G-01 | All model calls use canonical Engine path | `test_litellm_completion_only_in_engine` | **Green** |
| CP-G-02 | Trace records correct for complete() | `test_engine_persists_trace_and_routing_reason` | **Green** |
| CP-G-03 | Streaming calls remain correct + one usage/trace | `test_stream_persists_single_trace` | **Green** |
| CP-G-04 | Tool calls remain correct + traced | `test_tool_calls_json_traced` | **Green** |
| CP-G-05 | Fallback is traced | `test_engine_fallback_events_traced` / `test_fallback_rate_limit_traced` | **Green** |
| CP-G-06 | Budget policy works + reason code | `test_budget_reason_code_when_over_cap` | **Green** |
| CP-G-07 | Routing reason reproducible | `test_routing_reason_reproducible` | **Green** |
| CP-G-08 | Historical SQLite upgrades safely | `test_migration_11_adds_trace_columns_on_legacy_db` | **Green** |
| CP-G-09 | Trace privacy defaults safe | privacy + `test_private_defaults_minimal_hash_not_body` | **Green** |
| CP-G-10 | Experiments do not auto-apply | `test_experiments_never_auto_apply` | **Green** |
| CP-G-11 | Console metrics derive from real data | `test_operator_hubs_use_real_data` | **Green** |
| CP-G-12 | Private defaults remain private | doctor warn + `test_no_public_apache_proxy_scripts` + cookie tests | **Green** |

## Baseline suite

| Command | Result (2026-08-30 close-out) |
|---------|-------------------------------|
| `ruff check .` | pass |
| `pytest -m "not llm_e2e"` | **463 passed**, 1 deselected |

## Representative scenarios checklist

- [x] MCP / improver writes trace with `mcp_tool=improve_prompt`
- [x] Gateway non-stream completion traced (`selected_route`)
- [x] Gateway streaming single trace
- [x] Tool calling traced (names under minimal)
- [x] Fallback after simulated provider failure recorded
- [x] Local Ollama fallback floor remains in chain
- [x] Cloud provider via mocked LiteLLM
- [x] Console TODAY/QUALITY/ROUTING/PRIVACY from fixtures
- [x] Capture level `minimal` stores hash not body

## Definition of “program complete”

All CP-G-01…12 **green** with baseline suite green — **met**.
