#!/usr/bin/env bash
# Owner-only provision of XINAO researcher egress objects.
# Does not flip provider_egress_runtime_verified. Does not touch Dify.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export STATE_ROOT="${XINAO_EGRESS_STATE_ROOT:-D:/XINAO_RESEARCH_RUNTIME/state/xinao_skill/researcher_container/egress}"
PIN="$ROOT/image-pin.v1.json"
ALLOWLIST="${XINAO_EGRESS_ALLOWLIST:-$ROOT/allowlist.v1.json}"
TEMPLATE="$ROOT/squid.conf.template"

command -v docker >/dev/null || { echo "docker required"; exit 1; }

python3 -c '
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from render_squid_config import assert_image_pin, load_allowlist
pin = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert_image_pin(pin)
load_allowlist(Path(sys.argv[3]))
print("pin+allowlist preflight ok")
' "$ROOT" "$PIN" "$ALLOWLIST"

RENDERED="$(mktemp)"
RECEIPT="$(mktemp)"
python3 "$ROOT/render_squid_config.py" \
  --allowlist "$ALLOWLIST" \
  --template "$TEMPLATE" \
  --output "$RENDERED" \
  --receipt "$RECEIPT"
ACL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["provider_dstdomain_acl"])' "$RECEIPT")"
IMAGE="$(python3 -c 'import json,sys; pin=json.load(open(sys.argv[1],encoding="utf-8")); print(pin.get("image_digest") or pin["image_id"])' "$PIN")"

export XINAO_EGRESS_PROXY_IMAGE="$IMAGE"
export XINAO_EGRESS_PROVIDER_DSTDOMAIN_ACL="$ACL"

# Ignore comments; forbid host port publish and live Dify object reuse in active keys.
if grep -E '^[[:space:]]*ports:' "$ROOT/docker-compose.yaml"; then
  echo "host port publish forbidden in compose unless Owner amends with proof"
  exit 1
fi
if grep -E '^[[:space:]]*(container_name:[[:space:]]*ssrf_proxy|ssrf_proxy_network:)' \
  "$ROOT/docker-compose.yaml"; then
  echo "Dify cross-project object reuse forbidden"
  exit 1
fi
if grep -E '^[[:space:]]+ssrf_proxy:' "$ROOT/docker-compose.yaml"; then
  echo "Dify ssrf_proxy service reuse forbidden"
  exit 1
fi

docker compose -f "$ROOT/docker-compose.yaml" up -d

NET_ID="$(docker network inspect xinao_researcher_internal --format '{{.Id}}')"
PROXY_ID="$(docker inspect xinao-researcher-egress-proxy --format '{{.Id}}')"
PROXY_IMAGE_ID="$(docker inspect xinao-researcher-egress-proxy --format '{{.Image}}')"
INTERNAL="$(docker network inspect xinao_researcher_internal --format '{{.Internal}}')"
if [[ "$INTERNAL" != "true" ]]; then
  echo "internal network Internal!=true"
  exit 1
fi

mkdir -p "$STATE_ROOT"
export RECEIPT NET_ID PROXY_ID PROXY_IMAGE_ID
python3 -c '
import json, os
from pathlib import Path
from datetime import datetime, timezone
receipt = json.loads(Path(os.environ["RECEIPT"]).read_text(encoding="utf-8"))
posture = {
  "schema_version": "xinao.provider_egress_posture.v1",
  "lifecycle_state": "HEALTHY",
  "internal_network_name": "xinao_researcher_internal",
  "internal_network_id": os.environ["NET_ID"],
  "external_network_name": "xinao_provider_egress_ext",
  "proxy_container_name": "xinao-researcher-egress-proxy",
  "proxy_container_id": os.environ["PROXY_ID"],
  "proxy_image_id": os.environ["PROXY_IMAGE_ID"],
  "proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
  "proxy_listen_port": 3128,
  "allowlist_sha256": receipt["allowlist_sha256"],
  "proxy_config_sha256": receipt["proxy_config_sha256"],
  "provider_domains": receipt["domains"],
  "host_port_published": False,
  "dify_cross_project": False,
  "tls_interception": False,
  "provider_egress_runtime_verified": False,
  "verification_evidence": {
    "negative_suite": None,
    "positive_canary": None,
    "note": "Owner must run live negative suite + positive Grok canary before sealing verified=true in runtime lock."
  },
  "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
  "secrets_present": False,
}
blob = json.dumps(posture).lower()
for key in ("authorization", "api_key", "auth.json", "password"):
    if key in blob:
        raise SystemExit("posture redaction failed")
out = Path(os.environ["STATE_ROOT"]) / "current_posture.v1.json"
out.write_text(json.dumps(posture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"status":"PROVISIONED","posture_path":str(out),"provider_egress_runtime_verified":False}, sort_keys=True))
'

rm -f "$RENDERED" "$RECEIPT"
echo "Provision complete. provider_egress_runtime_verified remains false until Owner evidence seal."
