#!/usr/bin/env bash
# Install public HTTPS reverse proxy so Cursor Agent (cloud) can reach Ylang.
# LAN :8787 alone is not enough — Agent BYOK is not sent from your laptop.
set -euo pipefail

CONF_SRC="${CONF_SRC:-/srv/ylang/app/deploy/apache/ylang.stelliane.dev.conf}"
CONF_NAME="ylang.stelliane.dev.conf"
HOST_IP="${HOST_IP:-127.0.0.1}"
PUBLIC_HOST="ylang.stelliane.dev"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -f "${CONF_SRC}" ]]; then
  echo "Missing ${CONF_SRC}" >&2
  exit 1
fi

# Local resolver on this host often misses the public A record; pin for smoke tests.
if grep -qE "[[:space:]]${PUBLIC_HOST}([[:space:]]|$)" /etc/hosts; then
  sed -i -E "s/^.*[[:space:]]${PUBLIC_HOST}([[:space:]].*)?$/${HOST_IP} ${PUBLIC_HOST}/" /etc/hosts
else
  printf '%s %s\n' "${HOST_IP}" "${PUBLIC_HOST}" >> /etc/hosts
fi

a2enmod proxy proxy_http headers rewrite ssl >/dev/null
cp "${CONF_SRC}" "/etc/apache2/sites-available/${CONF_NAME}"
a2ensite "${CONF_NAME}" >/dev/null
apache2ctl configtest
systemctl reload apache2

echo "Enabled https://${PUBLIC_HOST} → 127.0.0.1:8787"
echo "--- local ---"
curl -sS -m 5 -o /tmp/ylang-health.json -w "health %{http_code}\n" "https://${PUBLIC_HOST}/health" || true
head -c 200 /tmp/ylang-health.json 2>/dev/null; echo
echo "--- via 8.8.8.8 ---"
# Force public resolution path for a second check when dig is available
if command -v dig >/dev/null; then
  PUB_IP="$(dig +short "${PUBLIC_HOST}" @8.8.8.8 A | head -1)"
  if [[ -n "${PUB_IP}" ]]; then
    curl -sS -m 8 -o /tmp/ylang-health-pub.json -w "public health %{http_code}\n" \
      --resolve "${PUBLIC_HOST}:443:${PUB_IP}" "https://${PUBLIC_HOST}/health" || true
    head -c 200 /tmp/ylang-health-pub.json 2>/dev/null; echo
  fi
fi

echo
echo "Cursor Settings → Models:"
echo "  OpenAI API Key:          value of YLANG_AUTH_TOKEN (not sk-...)"
echo "  Override OpenAI Base URL: https://${PUBLIC_HOST}/v1"
echo "  Model:                    gpt-4o-mini  (or ylang-mini)"
