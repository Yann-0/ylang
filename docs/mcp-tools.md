# MCP tools reference

Ylang exposes **11 MCP tools** via [FastMCP](https://github.com/modelcontextprotocol/python-sdk). All tools return JSON-serializable dicts. Errors use `ok: false` and an `error` string where applicable.

Transport: stdio (`python -m ylang`) or HTTP (`YLANG_TRANSPORT=http`, Bearer auth).

---

## improve_prompt

Expand a rough user prompt into a structured, actionable specification. **Propose-only** — returns text suggestions, never modifies files.

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `text` | string | yes | — | Raw user prompt |
| `tool` | string | yes | — | Calling tool name (e.g. `edit_file`, `grep`) — used for Cursor mode resolution |
| `model` | string | yes | — | Model slug or LiteLLM model string |
| `use_context` | boolean | no | `true` | Include conversation, facts, and reference prompts |
| `conversation` | array | no | `null` | `[{role, content}, ...]` prior turns |
| `mode` | string | no | `null` | Explicit Cursor mode: `agent`, `plan`, `debug`, `ask`, `multitask` |

### Response

```json
{
  "original": "fix the bug",
  "improved": "## Goal\n...",
  "changes": [
    {
      "kind": "scope",
      "description": "Added deliverables section",
      "before": "fix the bug",
      "after": "## Goal\n..."
    }
  ],
  "auto_apply_default": false,
  "validated": true,
  "cursor_mode": "debug",
  "mode_source": "prompt",
  "context_used": {
    "conversation_turns": 4,
    "facts_count": 2,
    "reference_prompts_count": 1,
    "had_conversation_input": true
  }
}
```

| Field | Description |
|-------|-------------|
| `validated` | `false` when the LLM output failed structural validation |
| `rejection_reason` | Present when `validated` is `false` |
| `auto_apply_default` | Hint whether auto-apply would be appropriate (always conservative for precision tools) |
| `changes[].kind` | One of: `clarity`, `format`, `constraint`, `example`, `scope` |

### Example

```json
{
  "text": "add dark mode toggle",
  "tool": "edit_file",
  "model": "claude-sonnet-4-5",
  "mode": "agent"
}
```

---

## save_template

Save a new **version** of a user template to the local library.

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `template_id` | string | yes | — | Stable identifier (e.g. `my-feature-spec`) |
| `name` | string | yes | — | Human-readable name |
| `body` | string | yes | — | Template body (may include `{{param}}` placeholders) |
| `params` | array | yes | — | `[{name, description?, default?}]` |
| `visibility` | string | no | `"private"` | `public` or `private` |
| `tags` | array | no | `[]` | Search tags |

### Response

```json
{
  "ok": true,
  "template_id": "my-feature-spec",
  "name": "Feature spec",
  "version": 2,
  "body": "...",
  "params": [],
  "source": "user",
  "visibility": "private",
  "tags": ["feature"],
  "created_at": "2026-07-04T12:00:00+00:00"
}
```

---

## recall_template

Fetch a template by id; optionally render with parameter values.

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `template_id` | string | yes | — | Template identifier |
| `version` | integer | no | latest | Specific version number |
| `param_values` | object | no | `null` | Map of param name → value for rendering |

### Response

`found: false` when missing. Otherwise includes full template fields plus optional `rendered` string.

---

## list_templates

List templates with latest-version metadata.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `source` | string | no | Filter: `seed`, `user`, or `learned` |
| `visibility` | string | no | Filter: `public` or `private` |

### Response

```json
{
  "ok": true,
  "templates": [
    {
      "template_id": "code-review",
      "name": "Code review",
      "latest_version": 1,
      "source": "seed",
      "updated_at": "2026-07-01T00:00:00+00:00",
      "param_names": ["language"],
      "visibility": "public",
      "tags": ["review"]
    }
  ]
}
```

---

## import_public_prompts

Import a public prompts CSV into the local library. **Idempotent** — existing `template_id`s are skipped.

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `url` | string | no | awesome-chatgpt-prompts URL | CSV source URL |

### Response

```json
{
  "ok": true,
  "imported": 42,
  "skipped": 10,
  "source_url": "https://..."
}
```

CLI equivalent: `python -m ylang.importer` or `scripts/import-public-prompts.sh`.

---

## remember

Persist a user fact under a named scope.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `fact` | string | yes | Fact text (non-empty) |
| `scope` | string | yes | `private` or `shareable` |

### Response

```json
{
  "ok": true,
  "id": 1,
  "fact": "Prefer Vitest over Jest",
  "scope": "private",
  "created_at": "2026-07-04T12:00:00+00:00"
}
```

Facts with scope `shareable` are included in `improve_prompt` context. `private` facts are also recalled for context (local-only).

---

## recall_facts

Return persisted facts, newest first.

### Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `scope` | string | no | all | Filter by `private` or `shareable` |
| `limit` | integer | no | `100` | Max rows |

### Response

```json
{
  "ok": true,
  "facts": [
    {
      "id": 1,
      "fact": "Prefer Vitest over Jest",
      "scope": "private",
      "created_at": "2026-07-04T12:00:00+00:00"
    }
  ]
}
```

---

## recall_usage

Return raw usage rows for a time window.

### Parameters

Provide **exactly one** window specifier:

| Name | Type | Description |
|------|------|-------------|
| `last_hours` | integer | Rolling window in hours |
| `last_days` | integer | Rolling window in days |
| `since` | string | ISO 8601 UTC start (use with `until`) |
| `until` | string | ISO 8601 UTC end |

Default when none specified: last 7 days.

### Response

```json
{
  "ok": true,
  "rows": [
    {
      "id": 1,
      "timestamp": "2026-07-04T12:00:00+00:00",
      "surface": "mcp",
      "activity": "improve:edit_file",
      "model_used": "anthropic/claude-3-5-sonnet-latest",
      "prompt_tokens": 1200,
      "cost": 0.003,
      "improver_fired": true,
      "improver_accepted": false,
      "latency_ms": 2400,
      "success": true
    }
  ]
}
```

---

## usage_summary

Return aggregated usage statistics.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `last_hours` | integer | Rolling window (mutually exclusive with `last_days`) |
| `last_days` | integer | Rolling window |

Default: last 7 days.

### Response

```json
{
  "ok": true,
  "total_requests": 150,
  "total_cost": 1.23,
  "total_tokens": 45000,
  "success_rate": 0.98,
  "by_activity": {"improve": 80, "code": 70},
  "by_model": {"anthropic/claude-3-5-sonnet-latest": 100},
  "model_costs": {"anthropic/claude-3-5-sonnet-latest": 0.95}
}
```

---

## detect_patterns

Detect repeated improver usage patterns and propose learned templates.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `window_days` | integer | `30` | Lookback period |

### Response

```json
{
  "ok": true,
  "patterns": [
    {
      "pattern_id": "add unit tests for",
      "sample_text": "add unit tests for",
      "occurrence_count": 5
    }
  ],
  "proposals": [
    {
      "suggested_template_id": "learned-add-unit-tests",
      "name": "Add unit tests",
      "body": "...",
      "params": [],
      "rationale": "Seen 5 times in the last 30 days"
    }
  ]
}
```

Patterns require at least **3 occurrences** in improver usage rows.

---

## save_learned_template

Persist an accepted pattern proposal as a `learned` source template.

### Parameters

Same shape as `save_template` (without `visibility` — learned templates are private by default).

### Response

Same as `save_template` with `source: "learned"`.

---

## Tool registration

Tools are registered in `src/ylang/mcp/tools.py` via `register_tools(server, deps)`. The server prints the tool list on startup:

```
tools (11): improve_prompt, save_template, recall_template, ...
```

## Related docs

- [Configuration](configuration.md) — model and auth settings
- [Cursor integration](cursor-integration.md) — hooks that call `improve_prompt`
- [Architecture](architecture.md) — request flow
