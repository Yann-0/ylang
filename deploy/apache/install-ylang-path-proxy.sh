#!/usr/bin/env bash
# Expose the Ylang gateway at https://<existing-host>/ylang/v1 — no new DNS record.
#
# Cursor's cloud refuses private-network targets ("Access to private networks is
# forbidden"), so the gateway needs a public HTTPS origin. This reuses a vhost
# whose hostname already resolves instead of adding a DNS A record.
set -euo pipefail

VHOST="${VHOST:-/etc/apache2/sites-available/010-stelliane.dev.conf}"
PUBLIC_HOST="${PUBLIC_HOST:-stelliane.dev}"
ENV_FILE="${ENV_FILE:-/srv/ylang/ylang.env}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -f "${VHOST}" ]]; then
  echo "Vhost not found: ${VHOST}" >&2
  echo "Set VHOST=/etc/apache2/sites-available/<file>.conf" >&2
  exit 1
fi

a2enmod proxy proxy_http headers >/dev/null

BACKUP="${VHOST}.bak.$(date +%Y%m%d-%H%M%S)"
cp -a "${VHOST}" "${BACKUP}"

python3 - "${VHOST}" <<'PY'
import re
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    text = handle.read()

block = """    # BEGIN ylang-gateway
    ProxyPass        /ylang/v1/ http://127.0.0.1:8787/v1/ timeout=600 retry=0
    ProxyPassReverse /ylang/v1/ http://127.0.0.1:8787/v1/
    ProxyPass        /ylang/v1 http://127.0.0.1:8787/v1 timeout=600 retry=0
    ProxyPassReverse /ylang/v1 http://127.0.0.1:8787/v1
    ProxyPass        /ylang/health http://127.0.0.1:8787/health
    ProxyPassReverse /ylang/health http://127.0.0.1:8787/health

    <LocationMatch "^/ylang/v1">
        SetEnv proxy-sendchunked 1
        RequestHeader unset Accept-Encoding
    </LocationMatch>
    # END ylang-gateway
"""

existing = re.search(
    r"[ \t]*# BEGIN ylang-gateway.*?# END ylang-gateway\n",
    text,
    re.DOTALL,
)
if existing:
    text = text[: existing.start()] + block + text[existing.end() :]
else:
    # Insert before the closing tag of the last *:443 VirtualHost.
    starts = [m.start() for m in re.finditer(r"<VirtualHost\s+\*:443\s*>", text)]
    if not starts:
        sys.exit("No <VirtualHost *:443> block found")
    close = text.find("</VirtualHost>", starts[-1])
    if close == -1:
        sys.exit("Unterminated <VirtualHost *:443> block")
    text = text[:close] + block + text[close:]

with open(path, "w", encoding="utf-8") as handle:
    handle.write(text)
print(f"ylang-gateway block written to {path}")
PY

if ! apache2ctl configtest; then
  echo "configtest failed — restoring ${BACKUP}" >&2
  cp -a "${BACKUP}" "${VHOST}"
  exit 1
fi

systemctl reload apache2

# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

echo
echo "--- health ---"
curl -sS -m 10 "https://${PUBLIC_HOST}/ylang/health" || true
echo
echo "--- models (Bearer) ---"
curl -sS -m 10 "https://${PUBLIC_HOST}/ylang/v1/models" \
  -H "Authorization: Bearer ${YLANG_AUTH_TOKEN}" | head -c 300 || true
echo
echo
echo "Cursor Settings -> Models:"
echo "  OpenAI API Key:           ${YLANG_AUTH_TOKEN}"
echo "  Override OpenAI Base URL: https://${PUBLIC_HOST}/ylang/v1"
echo "  Model:                    gpt-4o-mini"
echo
echo "Backup of previous vhost: ${BACKUP}"
