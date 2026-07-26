#!/bin/sh
set -eu

if [ "${1:-}" = "--xinao-entrypoint-probe" ]; then
    printf '%s\n' 'xinao.grok_container_entrypoint.v1'
    exit 0
fi

: "${GROK_HOME:?GROK_HOME is required}"

install -d -m 0755 "$GROK_HOME" "$GROK_HOME/hooks" "$GROK_HOME/logs"
install -m 0644 /inputs/transport-sandbox.toml "$GROK_HOME/sandbox.toml"
install -m 0644 /inputs/transport-config.toml "$GROK_HOME/config.toml"
: > "$GROK_HOME/hooks-paths"
chmod 0644 "$GROK_HOME/hooks-paths"

exec /usr/local/bin/grok "$@"
