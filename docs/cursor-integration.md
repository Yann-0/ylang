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

### Output file format

`.cursor/ylang-improved-prompt.md` contains:

- Improved prompt text (agent should follow this)
- `validated`, `changed`, `rejection_reason` metadata
- Original prompt for reference

### Environment overrides

| Variable | Effect |
|----------|--------|
| `YLANG_HOOK_DISABLED=1` | Skip improvement entirely |
| `YLANG_HOOK_MODEL` | Model slug for `improve_prompt` (default `claude-sonnet-4-5`) |
| `YLANG_MCP_URL` | Override MCP URL (default from `~/.cursor/mcp.json`) |
| `YLANG_AUTH_TOKEN` | Bearer token for HTTP MCP |

Hook logs append to `~/.cursor/hooks/ylang-improve-prompt.log`.

### Cursor API limitation

Cursor's documented `beforeSubmitPrompt` output only includes `continue` / `user_message`. The hook also emits `updated_input.prompt` for forward compatibility, but the **file + rule pattern** is the reliable integration path today.

## Project-level rules

The repository includes [`.cursor/rules/00-project.mdc`](../.cursor/rules/00-project.mdc) with Phase 1 guardrails for agents working in this codebase. Copy or adapt for your own projects as needed.

## Cursor mode awareness

`improve_prompt` resolves the active Cursor mode (`agent`, `plan`, `debug`, `ask`, `multitask`) from:

1. Explicit `mode` parameter (if passed by the hook/client)
2. Tool name
3. Prompt keywords
4. Default `agent`

Mode changes the structure and scope of improved prompts (e.g. plan mode avoids implementation deliverables). See [architecture.md](architecture.md#cursor-mode-resolution).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Hook silent, no markdown file | Check `~/.cursor/hooks/ylang-improve-prompt.log`; verify MCP URL and token |
| `validated=False`, `numbers changed` on a file/terminal `@` reference | Redeploy hook from `deploy/cursor/hooks/`; bare references now pass through without LLM improvement |
| `Unauthorized` from HTTP MCP | Set matching `YLANG_AUTH_TOKEN` in service env and mcp.json headers |
| Improvement always skipped | Remove `/ylang-skip` prefix; check `YLANG_HOOK_DISABLED` |
| Wrong Python in hook | Fix shebang in `ylang-improve-prompt.py` |

## Related docs

- [MCP tools reference](mcp-tools.md) — `improve_prompt` parameters
- [Configuration](configuration.md) — API keys, model prioritization, `ylang.env` layout
- [Installation](installation.md) — first-time setup
