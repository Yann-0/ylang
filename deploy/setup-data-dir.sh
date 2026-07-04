#!/usr/bin/env bash
# Prepare /srv/ylang/data for the ylang systemd service user.
# Mode 770 + group-owned DB files allow CLI users in group ylang to share the DB.
set -euo pipefail

DATA_DIR="${1:-/srv/ylang/data}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0 [data-dir]" >&2
  exit 1
fi

install -d -o ylang -g ylang -m 770 "${DATA_DIR}"

if [[ -f "${DATA_DIR}/ylang.db" ]]; then
  chown ylang:ylang "${DATA_DIR}/ylang.db" 2>/dev/null || true
  chown ylang:ylang "${DATA_DIR}"/ylang.db-* 2>/dev/null || true
  chmod 660 "${DATA_DIR}/ylang.db" 2>/dev/null || true
  chmod 660 "${DATA_DIR}"/ylang.db-* 2>/dev/null || true
fi

echo "Data directory ready: ${DATA_DIR} (owner ylang:ylang, mode 770)"
