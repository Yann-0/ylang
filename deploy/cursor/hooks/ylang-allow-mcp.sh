#!/usr/bin/env bash
# Auto-allow Ylang MCP tool calls (fail-open for other servers).
set -euo pipefail

input="$(cat)"
server_name="$(printf '%s' "$input" | /srv/ylang/app/.venv/bin/python -c 'import json,sys; p=json.load(sys.stdin); print(p.get("server_name") or p.get("serverName") or "")')"

if [[ "$server_name" == "ylang" || "$server_name" == *ylang* ]]; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi

printf '%s\n' '{"permission":"allow"}'
exit 0
