#!/usr/bin/env bash
# Install public HTTPS reverse proxy for the Ylang gateway.
set -euo pipefail

CONF_SRC="${CONF_SRC:-/srv/ylang/app/deploy/apache/ylang.stelliane.dev.conf}"
CONF_NAME="ylang.stelliane.dev.conf"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -f "${CONF_SRC}" ]]; then
  echo "Missing ${CONF_SRC}" >&2
  exit 1
fi

a2enmod proxy proxy_http headers rewrite ssl >/dev/null
cp "${CONF_SRC}" "/etc/apache2/sites-available/${CONF_NAME}"
a2ensite "${CONF_NAME}" >/dev/null
apache2ctl configtest
systemctl reload apache2

echo "Enabled https://ylang.stelliane.dev → 127.0.0.1:8787"
curl -sS -o /dev/null -w "health %{http_code}\n" https://ylang.stelliane.dev/health || true
