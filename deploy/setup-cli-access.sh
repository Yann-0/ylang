#!/usr/bin/env bash
# One-time setup: shared SQLite + env file access for admin CLI users (e.g. yann).
set -euo pipefail

WS_ROOT="${WS_ROOT:-/srv/ylang}"
DATA_DIR="${1:-${WS_ROOT}/data}"
ENV_FILE="${ENV_FILE:-${WS_ROOT}/ylang.env}"
# Space-separated login users to add to group ylang (override: CLI_USERS="yann alice")
CLI_USERS="${CLI_USERS:-yann}"
ENV_OWNER="${ENV_OWNER:-yann}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0 [data-dir]" >&2
  exit 1
fi

if ! getent group ylang >/dev/null; then
  groupadd --system ylang
fi

if ! id ylang >/dev/null 2>&1; then
  useradd --system --gid ylang --home-dir /nonexistent --shell /usr/sbin/nologin ylang
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/setup-data-dir.sh" "${DATA_DIR}"

for u in ${CLI_USERS}; do
  if id "${u}" >/dev/null 2>&1; then
    usermod -aG ylang "${u}"
    echo "Added ${u} to group ylang (log out/in or: newgrp ylang)"
  else
    echo "Warning: user ${u} not found, skipping" >&2
  fi
done

if [[ -f "${ENV_FILE}" ]]; then
  if ! id "${ENV_OWNER}" >/dev/null 2>&1; then
    ENV_OWNER="$(stat -c '%U' "${ENV_FILE}")"
  fi
  chown "${ENV_OWNER}:ylang" "${ENV_FILE}"
  chmod 640 "${ENV_FILE}"
  echo "Env file ready: ${ENV_FILE} (${ENV_OWNER}:ylang, mode 640)"
else
  echo "Note: ${ENV_FILE} not found; create it before starting the service." >&2
fi

echo "Verify as ${CLI_USERS%% *}:"
echo "  set -a && source ${ENV_FILE} && set +a"
echo "  ylang usage digest --last-days 7"
