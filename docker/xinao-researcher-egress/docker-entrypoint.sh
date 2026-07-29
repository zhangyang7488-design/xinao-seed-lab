#!/bin/bash
# XINAO researcher egress proxy entrypoint.
# Renders sealed allowlist into squid.conf and starts Squid.
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

export HTTP_PORT COREDUMP_DIR PROVIDER_DSTDOMAIN_ACL

echo "[ENTRYPOINT] rendering squid.conf from template (no private allowlist injection)"
awk '{
    while (match($0, /\${[A-Za-z_][A-Za-z_0-9]*}/)) {
        var = substr($0, RSTART+2, RLENGTH-3)
        val = ENVIRON[var]
        $0 = substr($0, 1, RSTART-1) val substr($0, RSTART+RLENGTH)
    }
    print
}' /etc/squid/squid.conf.template > /etc/squid/squid.conf

/usr/sbin/squid -Nz
echo "[ENTRYPOINT] starting squid on ${HTTP_PORT}"
exec /usr/sbin/squid -f /etc/squid/squid.conf -NYC 1
