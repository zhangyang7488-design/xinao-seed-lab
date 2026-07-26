#!/bin/sh
set -eu

real_bwrap=/usr/libexec/xinao/bwrap-real
tool_uid=65532
tool_gid=65532

if [ "${1:-}" = "--xinao-wrapper-probe" ]; then
    printf '%s\n' 'xinao.grok_bwrap_unprivileged_wrapper.v1'
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    exec "$real_bwrap" "$@"
fi

cap_eff=$(awk '$1 == "CapEff:" { print $2 }' /proc/self/status)
cap_prm=$(awk '$1 == "CapPrm:" { print $2 }' /proc/self/status)
cap_bnd=$(awk '$1 == "CapBnd:" { print $2 }' /proc/self/status)
no_new_privs=$(awk '$1 == "NoNewPrivs:" { print $2 }' /proc/self/status)

expected_caps=00000000000000c0
if [ "$cap_eff" != "$expected_caps" ] || \
   [ "$cap_prm" != "$expected_caps" ] || \
   [ "$cap_bnd" != "$expected_caps" ] || \
   [ "$no_new_privs" != 1 ]; then
    printf '%s\n' 'xinao bwrap wrapper refused unexpected outer privilege state' >&2
    exit 125
fi

exec /usr/bin/setpriv \
    --reuid="$tool_uid" \
    --regid="$tool_gid" \
    --clear-groups \
    --inh-caps=-all \
    --ambient-caps=-all \
    "$real_bwrap" "$@"
