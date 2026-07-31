#!/bin/sh
# Unprivileged bubblewrap helper for host/tool shell confinement.
# Does not mount Docker socket, auth, ledger, or outcome paths.
set -eu

if ! command -v bwrap >/dev/null 2>&1; then
  echo "bwrap missing" >&2
  exit 127
fi

LAB_ROOT="${XINAO_EPISODE_LAB_ROOT:-/episode-lab}"
TMP_ROOT="${TMPDIR:-/tmp}"

exec bwrap \
  --die-with-parent \
  --unshare-net \
  --unshare-pid \
  --ro-bind /usr /usr \
  --ro-bind /bin /bin \
  --ro-bind /lib /lib \
  --ro-bind-try /lib64 /lib64 \
  --ro-bind /etc/ssl /etc/ssl \
  --bind "$LAB_ROOT" "$LAB_ROOT" \
  --bind "$TMP_ROOT" /tmp \
  --dev /dev \
  --proc /proc \
  --chdir "$LAB_ROOT" \
  -- "$@"
