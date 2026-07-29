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
if ! grep -Fq 'http_access deny all' "${SQUID_CONF}"; then
  echo "[ENTRYPOINT] rendered squid.conf missing deny all" >&2
  exit 2
fi

/usr/sbin/squid -f "${SQUID_CONF}" -Nz
echo "[ENTRYPOINT] starting squid on ${HTTP_PORT}"
exec /usr/sbin/squid -f "${SQUID_CONF}" -NYC 1
