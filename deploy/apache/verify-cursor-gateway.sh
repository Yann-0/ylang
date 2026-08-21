#!/usr/bin/env bash
# Smoke-test the public Cursor -> Ylang -> Ollama path.
#
# Usage:
#   ./verify-cursor-gateway.sh                                  # path proxy on stelliane.dev
#   BASE_URL=https://ylang.stelliane.dev/v1 ./verify-cursor-gateway.sh
set -euo pipefail

ENV_FILE="${ENV_FILE:-/srv/ylang/ylang.env}"
BASE_URL="${BASE_URL:-https://stelliane.dev/ylang/v1}"
HEALTH_URL="${HEALTH_URL:-${BASE_URL%/v1}/health}"

# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

TOKEN="${YLANG_AUTH_TOKEN:?YLANG_AUTH_TOKEN missing in ${ENV_FILE}}"

echo "base url: ${BASE_URL}"
echo
echo "1) health"
curl -sS -m 10 -w '\n  http %{http_code}\n' "${HEALTH_URL}"
echo
echo "2) models (Bearer)"
curl -sS -m 10 -w '\n  http %{http_code}\n' "${BASE_URL}/models" \
  -H "Authorization: Bearer ${TOKEN}" | head -c 400
echo
echo "3) chat gpt-4o-mini -> expect local Ollama"
curl -sS -m 120 -w '\n  http %{http_code}\n' "${BASE_URL}/chat/completions" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Reply with exactly: LOCAL_OK"}],"max_tokens":16}'
echo
echo "4) latest gateway usage rows"
sqlite3 /srv/ylang/data/ylang.db \
  "SELECT id, timestamp, model_used, success, latency_ms FROM usage WHERE surface='gateway' ORDER BY id DESC LIMIT 3;"
