# 02 — Source contracts

Live recheck 2026-09-13 via GitHub HTTPS (not from adapter configuration).

## prompts-chat — LIVE_SOURCE_VERIFIED (eligible)

| Field | Value |
|-------|-------|
| Identity | `f/prompts.chat` SHA `f78a1c5136fa080155d928e0d7e2b4a41ddef03e` (same lineage as `f/awesome-chatgpt-prompts`) |
| Eligible content | `prompts.csv` present (`act`/`prompt` columns; 5 769 655 bytes). **2 169** DictReader records with both fields set. Physical file has 121 758 newlines because prompt bodies contain embedded newlines — that is not 122k prompts. |
| License | Dual-license LICENSE: prompt data CC0 1.0; code MIT. Markers include `cc0`. |
| Adapter | `PromptsChatAdapter` |

## github-awesome-copilot — incompatible (honest disable)

| Field | Value |
|-------|-------|
| Identity | `github/awesome-copilot` SHA `7568a482ce2df38f8965ab5336a3220db796a4ba` |
| Tree | 2837 blobs, `truncated=false` |
| `*.prompt.md` | **0** |
| `prompts/` / `.github/prompts/` | **0** prompt files |
| Actual layout | `skills/` (~1208), `agents/` (~222), `instructions/` (~193), extensions/plugins |
| v1 policy | Do **not** convert agents/skills/MCP/instructions into ordinary prompts |
| Product action | `compatibility_status=incompatible`; enable refused |

A successful **fixture** tree with `prompts/*.prompt.md` still imports those
files only. That does not make the live repo eligible.

## fabric-patterns — LIVE_SOURCE_VERIFIED (eligible)

| Field | Value |
|-------|-------|
| Identity | `danielmiessler/Fabric` SHA `b682dad740f24e85ce9a48d23babc6780dd476ac` |
| Eligible content | 255 `data/patterns/*/system.md`; tree not truncated (849 blobs) |
| License | MIT (`permission is hereby granted, free of charge`) |

## How to re-verify

```bash
YLANG_NETWORK_TESTS=1 pytest -m network
```

Default CI does not hit the network. A green simulated execute is not live
source verification.
