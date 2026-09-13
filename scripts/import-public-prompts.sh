#!/usr/bin/env bash
# Refresh prompts.chat into candidate quarantine (not auto-promoted).
set -euo pipefail

DB_PATH="${YLANG_STORAGE_PATH:-/srv/ylang/data/ylang.db}"
VENV_PYTHON="${VENV_PYTHON:-/srv/ylang/.venv/bin/python}"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Python venv not found: ${VENV_PYTHON}" >&2
  exit 1
fi

if [[ "${EUID}" -eq 0 ]]; then
  exec -u ylang "${VENV_PYTHON}" -m ylang prompts refresh prompts-chat "$@"
fi

if [[ -w "${DB_PATH}" ]]; then
  exec "${VENV_PYTHON}" -m ylang prompts refresh prompts-chat "$@"
fi

echo "Need write access to ${DB_PATH}. Try:" >&2
echo "  sudo -u ylang ${VENV_PYTHON} -m ylang prompts refresh prompts-chat" >&2
exit 1
