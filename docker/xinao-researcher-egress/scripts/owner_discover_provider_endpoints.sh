#!/usr/bin/env bash
# Owner-only credential-safe provider endpoint discovery helper scaffold.
set -euo pipefail
OUT_DIR="${1:-./discovery_capture}"
mkdir -p "$OUT_DIR"
cat > "$OUT_DIR/README.txt" <<'DOC'
1. From a non-researcher network, run one minimal authenticated grok call: --model grok-4.5, tool-free, max-turns 1.
2. Capture CONNECT host:443 targets via temporary logging proxy or engine flow log.
3. Redact Authorization, cookies, API keys, auth.json bytes before any file lands on disk.
4. Record DNS question names and CNAME chains; seal names, not transient IPs.
5. Build minimal dstdomain list; write allowlist.v1.json domains; compute allowlist_sha256.
6. Re-render squid config; run second canary; only then consider production use.
7. Never set provider_egress_runtime_verified=true from this script.
DOC
python3 -c '
import json, sys
from pathlib import Path
from datetime import datetime, timezone
root = Path(sys.argv[1])
scaffold = {
  "schema_version": "xinao.provider_egress_discovery_receipt.v1",
  "status": "SCAFFOLD_ONLY",
  "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
  "observed_connect_hosts": [],
  "observed_ports": [443],
  "websocket_upgrade_observed": None,
  "redaction": {
    "authorization_headers_stripped": True,
    "auth_json_bytes_forbidden": True,
    "api_keys_forbidden": True,
  },
  "provider_egress_runtime_verified": False,
  "secrets_present": False,
  "next_step": "Owner fills observed_connect_hosts after redacted lab capture",
}
(root / "discovery_receipt.v1.json").write_text(json.dumps(scaffold, indent=2, sort_keys=True)+"\n", encoding="utf-8")
print(json.dumps({"status":"SCAFFOLD_READY","path":str(root)}, sort_keys=True))
' "$OUT_DIR"
