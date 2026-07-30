#!/bin/bash
# XINAO researcher egress proxy entrypoint.
# Renders sealed allowlist into squid.conf on writable tmpfs and starts Squid.
# Deliberately does NOT generate private-network allow rules or Dify sandbox bridges.

set -euo pipefail

echo "[ENTRYPOINT] ensure snakeoil cert present for squid package layout"
if [ ! -f /etc/ssl/private/ssl-cert-snakeoil.key ]; then
  /usr/sbin/make-ssl-cert generate-default-snakeoil --force-overwrite >/dev/null 2>&1 || true
fi

mkdir -p /var/log/squid /var/spool/squid
chown -R proxy:proxy /var/log/squid /var/spool/squid 2>/dev/null || true

tail -F /var/log/squid/access.log 2>/dev/null &
tail -F /var/log/squid/error.log 2>/dev/null &
tail -F /var/log/squid/cache.log 2>/dev/null &

: "${HTTP_PORT:=3128}"
: "${COREDUMP_DIR:=/var/spool/squid}"
: "${PROVIDER_DSTDOMAIN_ACL:=acl provider_domains dstdomain .invalid.xinao.local}"

# Fail closed on env injection into template substitution (HTTP_PORT / COREDUMP_DIR
# / PROVIDER_DSTDOMAIN_ACL are expanded by awk into squid.conf). A newline in
# HTTP_PORT can insert `http_access allow all` before the deny rules and win.
case "${HTTP_PORT}" in
  *$'\n'*|*$'\r'*|*[!0-9]*)
    echo "[ENTRYPOINT] HTTP_PORT must be a single decimal TCP port" >&2
    exit 2
    ;;
esac
if ! printf '%s' "${HTTP_PORT}" | grep -Eq '^[1-9][0-9]{0,4}$'; then
  echo "[ENTRYPOINT] HTTP_PORT out of range or malformed" >&2
  exit 2
fi
if [ "${HTTP_PORT}" -lt 1 ] || [ "${HTTP_PORT}" -gt 65535 ]; then
  echo "[ENTRYPOINT] HTTP_PORT out of range" >&2
  exit 2
fi
case "${COREDUMP_DIR}" in
  *$'\n'*|*$'\r'*|*[[:space:]]*|*..*)
    echo "[ENTRYPOINT] COREDUMP_DIR must be a single absolute path without whitespace" >&2
    exit 2
    ;;
esac
if ! printf '%s' "${COREDUMP_DIR}" | grep -Eq '^/[A-Za-z0-9._/-]+$'; then
  echo "[ENTRYPOINT] COREDUMP_DIR path rejected" >&2
  exit 2
fi

# Fail closed on ACL env injection (newlines / extra http_access / ssl_bump).
case "${PROVIDER_DSTDOMAIN_ACL}" in
  *$'\n'*|*$'\r'*)
    echo "[ENTRYPOINT] PROVIDER_DSTDOMAIN_ACL must be a single line" >&2
    exit 2
    ;;
esac
if ! printf '%s' "${PROVIDER_DSTDOMAIN_ACL}" | grep -Eq '^acl provider_domains dstdomain '; then
  echo "[ENTRYPOINT] PROVIDER_DSTDOMAIN_ACL must start with acl provider_domains dstdomain" >&2
  exit 2
fi
if printf '%s' "${PROVIDER_DSTDOMAIN_ACL}" | grep -Eiq 'http_access|ssl_bump|client_localnet|ssrf_proxy'; then
  echo "[ENTRYPOINT] PROVIDER_DSTDOMAIN_ACL contains forbidden ACL fragments" >&2
  exit 2
fi

export HTTP_PORT COREDUMP_DIR PROVIDER_DSTDOMAIN_ACL

# Rootfs is read_only; write rendered conf onto tmpfs spool, never /etc/squid.
SQUID_CONF="${COREDUMP_DIR}/squid.conf"
echo "[ENTRYPOINT] rendering squid.conf from template onto ${SQUID_CONF}"
awk '{
    while (match($0, /\${[A-Za-z_][A-Za-z_0-9]*}/)) {
        var = substr($0, RSTART+2, RLENGTH-3)
        val = ENVIRON[var]
        $0 = substr($0, 1, RSTART-1) val substr($0, RSTART+RLENGTH)
    }
    print
}' /etc/squid/squid.conf.template > "${SQUID_CONF}"

if grep -Eiq 'http_access allow client_localnet|ssl_bump|ssrf_proxy' "${SQUID_CONF}"; then
  echo "[ENTRYPOINT] rendered squid.conf failed forbidden fragment check" >&2
  exit 2
fi
# First-match http_access: any allow before the terminal deny all is a breakout.
if grep -Eiq '^[[:space:]]*http_access[[:space:]]+allow[[:space:]]+all([[:space:]]|$)' "${SQUID_CONF}"; then
  echo "[ENTRYPOINT] rendered squid.conf forbids http_access allow all" >&2
  exit 2
fi
if ! grep -Fq 'http_access deny all' "${SQUID_CONF}"; then
  echo "[ENTRYPOINT] rendered squid.conf missing deny all" >&2
  exit 2
fi
# Emit live-config hash so Owner posture can bind observed bytes, not offline render only.
if command -v sha256sum >/dev/null 2>&1; then
  LIVE_CONF_SHA256="$(sha256sum "${SQUID_CONF}" | awk '{print $1}')"
  echo "[ENTRYPOINT] live_proxy_config_sha256=${LIVE_CONF_SHA256}"
fi

/usr/sbin/squid -f "${SQUID_CONF}" -Nz
echo "[ENTRYPOINT] starting squid on ${HTTP_PORT}"
exec /usr/sbin/squid -f "${SQUID_CONF}" -NYC 1
