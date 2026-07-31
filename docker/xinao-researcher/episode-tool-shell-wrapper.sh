#!/bin/sh
# Episode tool shell wrapper: routes shell ops through bwrap when available.
# Fail closed if XINAO_TOOL_EXEC_BWRAP=require and bwrap is missing.
set -eu

MODE="${XINAO_TOOL_EXEC_BWRAP:-require}"
WRAPPER_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BWRAP_HELPER="${XINAO_TOOL_BWRAP_BIN:-$WRAPPER_DIR/grok-bwrap-unprivileged-wrapper}"

case "$MODE" in
  require|1|on|true|yes|REQUIRE)
    if ! command -v bwrap >/dev/null 2>&1 && [ ! -x "$BWRAP_HELPER" ]; then
      echo "episode-tool-shell-wrapper: bwrap required but missing" >&2
      exit 126
    fi
    if [ -x "$BWRAP_HELPER" ]; then
      exec "$BWRAP_HELPER" "$@"
    fi
    exec bwrap --die-with-parent --unshare-net -- "$@"
    ;;
  auto|AUTO)
    if command -v bwrap >/dev/null 2>&1 || [ -x "$BWRAP_HELPER" ]; then
      if [ -x "$BWRAP_HELPER" ]; then
        exec "$BWRAP_HELPER" "$@"
      fi
      exec bwrap --die-with-parent --unshare-net -- "$@"
    fi
    exec "$@"
    ;;
  0|off|false|no|OFF)
    exec "$@"
    ;;
  *)
    echo "episode-tool-shell-wrapper: unknown bwrap mode: $MODE" >&2
    exit 2
    ;;
esac
