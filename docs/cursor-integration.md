# Cursor integration

Ylang integrates with [Cursor](https://cursor.com) as an MCP server and optionally via **global hooks** that auto-improve every user prompt before the agent sees it.

Templates for hooks and rules live in [`deploy/cursor/`](../deploy/cursor/).

## MCP server setup

### stdio (local development)

Add to `.cursor/mcp.json` in your project or `~/.cursor/mcp.json` globally:

```json
{
  "mcpServers": {
    "ylang": {
      "command": "python",
      "args": ["-m", "ylang"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

When developing from a checkout without `pip install -e .`, add:

```json
"env": {
  "PYTHONPATH": "${workspaceFolder}/src",
  "ANTHROPIC_API_KEY": "sk-ant-..."
}
```

### HTTP (shared / production instance)

When Ylang runs as a systemd service on HTTP transport:

```json
{
  "mcpServers": {
    "ylang": {
      "url": "http://127.0.0.1:8787/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_YLANG_AUTH_TOKEN"
      }
    }
  }
}
```

See [deployment.md](deployment.md) for service setup.

## OpenAI gateway (route real coding traffic)

To send Cursor **chat/agent** requests through Ylang's activity router (not just the improver MCP tool), add a custom OpenAI-compatible provider:

| Setting | Value |
|---------|-------|
| Base URL | `http://<host>:8787/v1` |
| API key | Your `YLANG_AUTH_TOKEN` |
| Model | `route-code` (or `route-search`, `route-reason`, `route-other`) |

Passthrough models (e.g. `ollama/qwen2.5`, `gpt-4o`) are also accepted. Requires `YLANG_TRANSPORT=http`. See [gateway.md](gateway.md) for curl examples and streaming notes.

MCP improver hooks and gateway routing are complementary: hooks improve prompts; the gateway routes model completions.

**Avoid double LLM calls:** use either the global `beforeSubmitPrompt` hook *or* gateway routing for agent chat — not both on the same traffic. Typical setup: hooks for prompt improvement (MCP `improve_prompt`), gateway for model selection on agent completions. Set `YLANG_HOOK_DISABLED=1` when testing gateway-only routing. See [configuration.md](configuration.md#hooks-vs-gateway).

## Learned templates workflow

Close the learning loop from repeated improver prompts to saved templates:

1. **Detect** — MCP `detect_patterns` or CLI `ylang patterns suggest --window-days 30`
2. **Review** — inspect proposals (template id, rationale, sample text)
3. **Save** — CLI `ylang patterns apply --index 1 --yes`, or MCP `save_learned_template`

Example:

```bash
ylang patterns suggest
ylang patterns apply --index 1 --yes
# Or interactive: ylang patterns apply
```

Saved learned templates are automatically included in future `improve_prompt` context (top N by recency; `YLANG_LEARNED_TEMPLATE_LIMIT`, default 2).

Weekly digest (CLI/cron; optional desktop notify when `usage_digest_enabled` or `--notify`):

```bash
ylang usage digest --last-days 7
ylang usage digest --last-days 7 --notify
```

## Auto prompt improvement (global hooks)

This workflow calls `improve_prompt` on **every user message** and writes the result to `.cursor/ylang-improved-prompt.md` in the workspace. A global Cursor rule tells the agent to treat that file as the canonical task.

### Install globally

1. Copy hook config:
   ```bash
   cp deploy/cursor/hooks.json ~/.cursor/hooks.json
   ```

2. Copy hook scripts (make executable):
   ```bash
   cp deploy/cursor/hooks/* ~/.cursor/hooks/
   chmod +x ~/.cursor/hooks/*.py ~/.cursor/hooks/*.sh
   ```

3. Copy the agent rule:
   ```bash
   cp deploy/cursor/ylang-auto-improve.mdc ~/.cursor/rules/ylang-auto-improve.mdc
   ```

4. Ensure `~/.cursor/mcp.json` defines the `ylang` server (stdio or HTTP as above).

5. Update the shebang in `ylang-improve-prompt.py` if your Python path differs from the template.

### Hook behavior

| Hook | Script | Purpose |
|------|--------|---------|
| `sessionStart` | `ylang-session-start.py` | Session initialization |
| `beforeSubmitPrompt` | `ylang-improve-prompt.py` | Call `improve_prompt`, write markdown file |
| `beforeMCPExecution` | `ylang-allow-mcp.sh` | Allow MCP calls to the `ylang` server |

The `beforeSubmitPrompt` hook:

- Reads conversation from `CURSOR_TRANSCRIPT_PATH` when available
- Calls Ylang `improve_prompt` via HTTP MCP client
- Writes `.cursor/ylang-improved-prompt.md` with original, improved, validation status
- Passes through bare file/terminal references unchanged (`validated=True`, no LLM call)
- Skips meta-prompts (prior hook output, `/loop`, `/YOLO`, `/ylang-skip`)
- Skips improvement when the prompt contains **`ylang-off`** / **`/ylang-off`** (see below)
- After pulling hook changes, re-copy/sync scripts from `deploy/cursor/hooks/` into `~/.cursor/hooks/` (they are not always symlinks)

### Bypass improvement with `ylang-off`

Put **`ylang-off`** (or **`/ylang-off`**) anywhere in your Cursor chat message to skip Ylang prompt improvement for that submit only.

| Form | Example |
|------|---------|
| Inline token | `ylang-off fix the flaky test in auth` |
| Slash form | `/ylang-off` then your task on the next line |
| Mid-message | `Please do this carefully. ylang-off` |

**What happens:**

1. The hook does **not** call MCP `improve_prompt` (no LLM cost / latency for that turn).
2. The marker is **stripped** from the text Cursor’s agent receives.
3. The hook logs `skipped (ylang-off)` to `~/.cursor/hooks/ylang-improve-prompt.log`.
4. Matching is case-insensitive and token-based (`my-ylang-off-tool` is **not** matched).

**Related skips (unchanged):**

| Mechanism | Scope |
|-----------|--------|
| `ylang-off` / `/ylang-off` | Per-message, anywhere in the prompt; marker removed |
| `/ylang-skip` | Prefix-only skip (legacy); prompt left as-is |
| `/loop`, `/YOLO` | Prefix-only skip for Cursor slash commands |
| `YLANG_HOOK_DISABLED=1` | Global kill-switch for the hook |

### Output file format

`.cursor/ylang-improved-prompt.md` contains:

- Improved prompt text (agent should follow this)
- Hook metadata: `validated`, `changed`, `rejection_reason` (these are **hook file fields**, not MCP `improve_prompt` response fields)
- Original prompt for reference

### Environment overrides

| Variable | Effect |
|----------|--------|
| `YLANG_HOOK_DISABLED=1` | Skip improvement entirely |
| `YLANG_HOOK_MODEL` | Model for `improve_prompt` (default `auto` → `YLANG_MODELS_IMPROVE`) |
| `YLANG_HOOK_TIMEOUT_SEC` | MCP call timeout in seconds (default `15`); on timeout the hook fail-opens |
| `YLANG_IMPROVER_TIMEOUT_SEC` | Server-side improver LLM budget in seconds (default `12`; `0` disables) |
| `YLANG_MCP_URL` | Override MCP URL (default from `~/.cursor/mcp.json`) |
| `YLANG_AUTH_TOKEN` | Bearer token for HTTP MCP |

Hook logs append to `~/.cursor/hooks/ylang-improve-prompt.log`.

### Cursor API limitation

The hook honors `auto_apply_default` from `improve_prompt`:

- **`true`** (default for most tools/modes) — emits `updated_input.prompt` when the prompt changed; also writes `.cursor/ylang-improved-prompt.md`.
- **`false`** (precision tools, `plan`/`debug` modes) — emits `user_message` with a review notice instead of silent `updated_input`; sidecar file is still written.

Cursor's documented `beforeSubmitPrompt` output includes `continue` / `user_message`. The **file + rule pattern** remains the reliable integration path; `updated_input` is forward-compatible when Cursor adds support.

## Project-level rules

The repository includes [`.cursor/rules/00-project.mdc`](../.cursor/rules/00-project.mdc) with Phase 1 guardrails for agents working in this codebase. Copy or adapt for your own projects as needed.

## Cursor mode awareness

`improve_prompt` resolves the active Cursor mode (`agent`, `plan`, `debug`, `ask`, `multitask`) from:

1. Explicit `mode` parameter (if passed by the hook/client)
2. MCP tool name defaults (`edit_file`/`grep` → `agent`, `read_file`/`search` → `ask`, `analyze` → `plan`)
3. Tool name aliases and prompt keywords
4. Default `agent`

Mode changes the structure and scope of improved prompts (e.g. plan mode avoids implementation deliverables). See [architecture.md](architecture.md#cursor-mode-resolution).

### Parallel workers and multitask

`improve_prompt` actively shapes prompts to leverage Cursor's parallel subagents and background agents:

- **multitask mode** — decomposes work into independent workstreams and adds a *Parallelization plan* that marks which streams run concurrently (spawn parallel/background subagents) vs sequentially, plus an integration/merge step. Optimizes for wall-clock time.
- **plan mode** — starts with read-only exploration, compares options with trade-offs, and produces a phased roadmap that marks parallelizable vs sequential phases so execution can later fan out to parallel workers.
- **auto-detection** — even in `agent` mode, when a prompt has multiple independent deliverables (explicit parallel keywords, ≥2 list items, or ≥3 distinct action verbs), Ylang injects a parallelization directive so the improved spec groups concurrently-runnable work and recommends batching independent tool calls.

Only genuinely independent work is parallelized; edits to shared files stay sequential and no unrelated work is added (improver remains propose-only).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Hook silent, no markdown file | Check `~/.cursor/hooks/ylang-improve-prompt.log`; verify MCP URL and token |
| `validated=False`, `numbers changed` on a file/terminal `@` reference | Redeploy hook from `deploy/cursor/hooks/`; bare references now pass through without LLM improvement |
| `Unauthorized` from HTTP MCP | Set matching `YLANG_AUTH_TOKEN` in service env and mcp.json headers |
| Improvement always skipped | Remove `/ylang-skip` prefix or accidental `ylang-off` / `/ylang-off` in the message; check `YLANG_HOOK_DISABLED`; look for `skipped (ylang-off)` in the hook log |
| Want raw prompt this turn only | Add `ylang-off` anywhere in the message (see [Bypass improvement with ylang-off](#bypass-improvement-with-ylang-off)) |
| `ylang-off` ignored / still improved | Re-sync `deploy/cursor/hooks/ylang-improve-prompt.py` → `~/.cursor/hooks/` and restart Cursor |
| `validated=False`, `rejection_reason: length ratio out of bounds` on a very short prompt (e.g. `let's do all`) | Upgrade Ylang; short prompts now use relaxed length bounds and a deterministic multitask/agent fallback when the model under-expands |
| Wrong Python in hook | Fix shebang in `ylang-improve-prompt.py` |
| `Bad Request — This model does not support custom API keys` | See [First-party models vs Ylang gateway](#first-party-models-vs-ylang-gateway) |

### First-party models vs Ylang gateway

Cursor **first-party** models (e.g. **Cursor Grok Beta High**, Grok, Composer) reject requests when an **OpenAI API Key** and/or **Override OpenAI Base URL** is enabled — including a Ylang OpenAI-compatible gateway. Error:

> Bad Request — This model does not support custom API keys.

**Workaround:**

1. **Cursor Settings → Models:** turn **OFF** OpenAI API Key and Override OpenAI Base URL (or press `Ctrl+Shift+0` to toggle the OpenAI key).
2. Then use Grok / Composer from the model picker on your Cursor plan.
3. **OR** keep BYOK / Override Base URL on and use **Auto** or BYOK-supported providers (OpenAI, Anthropic, Google, Azure, Bedrock) — not Grok/Composer.
4. Toggle with `Ctrl+Shift+0` when switching between first-party Grok and the Ylang gateway.
5. These settings live on the **Cursor desktop client** (e.g. Windows), not on the SSH remote.
6. **xAI is not a Cursor BYOK provider** — use Grok from the model picker on a paid plan; do not expect an xAI API key to unlock first-party Grok while a custom OpenAI base URL is set.

See [gateway.md](gateway.md#cursor-setup) for Ylang Base URL setup when the override is enabled.

## Related docs

- [MCP tools reference](mcp-tools.md) — `improve_prompt` parameters
- [Configuration](configuration.md) — API keys, model prioritization, `ylang.env` layout
- [Installation](installation.md) — first-time setup
