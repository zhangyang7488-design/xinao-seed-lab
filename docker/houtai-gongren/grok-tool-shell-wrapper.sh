#!/bin/sh
set -eu

real_bash=/usr/libexec/xinao/bash-real
real_bwrap=/usr/libexec/xinao/bwrap-real
empty_profile=/usr/libexec/xinao/empty-grok-profile
grok_home=/grok-home/.grok
tool_uid=65532
tool_gid=65532

if [ "${1:-}" = "--xinao-wrapper-probe" ]; then
    printf '%s\n' 'xinao.grok_tool_shell_wrapper.v1'
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    exec "$real_bash" "$@"
fi

case "$PWD" in
    /workspace|/workspace/*) ;;
    *)
        printf '%s\n' 'xinao tool shell refused a working directory outside /workspace' >&2
        exit 125
        ;;
esac

cap_eff=$(awk '$1 == "CapEff:" { print $2 }' /proc/self/status)
cap_prm=$(awk '$1 == "CapPrm:" { print $2 }' /proc/self/status)
cap_bnd=$(awk '$1 == "CapBnd:" { print $2 }' /proc/self/status)
no_new_privs=$(awk '$1 == "NoNewPrivs:" { print $2 }' /proc/self/status)
expected_caps=00000000000000c0
if [ "$cap_eff" != "$expected_caps" ] || \
   [ "$cap_prm" != "$expected_caps" ] || \
   [ "$cap_bnd" != "$expected_caps" ] || \
   [ "$no_new_privs" != 1 ]; then
    printf '%s\n' 'xinao tool shell refused unexpected transport privilege state' >&2
    exit 125
fi

exec /usr/bin/setpriv \
    --reuid="$tool_uid" \
    --regid="$tool_gid" \
    --clear-groups \
    --inh-caps=-all \
    --ambient-caps=-all \
    "$real_bwrap" \
    --unshare-user \
    --unshare-pid \
    --die-with-parent \
    --ro-bind / / \
    --dev-bind /dev /dev \
    --proc /proc \
    --bind /workspace /workspace \
    --bind /tmp /tmp \
    --ro-bind "$empty_profile" "$grok_home" \
    --setenv HOME /tmp \
    --setenv TMPDIR /tmp \
    --chdir "$PWD" \
    "$real_bash" "$@"
