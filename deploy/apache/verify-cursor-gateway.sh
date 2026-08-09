#!/usr/bin/env bash
# Smoke-test the public Cursor → Ylang → Ollama path.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
ENV_FILE="${ENV_FILE:-/srv/ylang/ylang.env}"
HOST="${YLANG_PUBLIC_HOST:-ylang.stelliane.dev}"

# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

TOKEN="${YLANG_AUTH_TOKEN:?YLANG_AUTH_TOKEN missing in ${ENV_FILE}}"

echo "1) health"
curl -sS -m 10 "https://${HOST}/health"
echo
echo "2) models (Bearer)"
curl -sS -m 10 "https://${HOST}/v1/models" \
  -H "Authorization: Bearer ${TOKEN}" | head -c 400
echo
echo "3) chat gpt-4o-mini → expect local Ollama"
curl -sS -m 120 "https://${HOST}/v1/chat/completions" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Reply with exactly: LOCAL_OK"}],"max_tokens":16}'
echo
echo "4) latest gateway usage row"
sqlite3 /srv/ylang/data/ylang.db \
  "SELECT id, timestamp, model_used, success, latency_ms FROM usage WHERE surface='gateway' ORDER BY id DESC LIMIT 3;"
