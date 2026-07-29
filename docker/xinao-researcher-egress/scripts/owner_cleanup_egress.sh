#!/usr/bin/env bash
# Owner-only cleanup of XINAO researcher egress objects. Never touches Dify.
set -euo pipefail
export STATE_ROOT="${XINAO_EGRESS_STATE_ROOT:-D:/XINAO_RESEARCH_RUNTIME/state/xinao_skill/researcher_container/egress}"

while read -r id; do
  [ -z "$id" ] && continue
  name="$(docker inspect -f '{{.Name}}' "$id" 2>/dev/null || true)"
  case "$name" in
    /xinao-researcher-*) docker rm -f "$id" >/dev/null 2>&1 || true ;;
  esac
done <<EOF
$(docker ps -aq --filter "label=io.xinao.researcher.chain=dedicated-xinao-science" 2>/dev/null || true)
EOF

proxy_removed=0
if docker rm -f xinao-researcher-egress-proxy >/dev/null 2>&1; then
  proxy_removed=1
fi

removed_networks=""
for net in xinao_researcher_internal xinao_provider_egress_ext; do
  if docker network rm "$net" >/dev/null 2>&1; then
    if [ -n "$removed_networks" ]; then
      removed_networks="${removed_networks},${net}"
    else
      removed_networks="${net}"
    fi
  fi
done

for name in ssrf_proxy ssrf_proxy_network; do
  if docker inspect "$name" >/dev/null 2>&1; then
    echo "left Dify object untouched: $name"
  fi
done

mkdir -p "$STATE_ROOT"
export PROXY_REMOVED="$proxy_removed"
export REMOVED_NETWORKS_CSV="$removed_networks"
python3 -c '
import json, os
from pathlib import Path
from datetime import datetime, timezone
root = Path(os.environ["STATE_ROOT"])
nets = [n for n in os.environ.get("REMOVED_NETWORKS_CSV", "").split(",") if n]
receipt = {
  "schema_version": "xinao.provider_egress_cleanup_receipt.v1",
  "cleaned_at": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
  "proxy_removed_observed": os.environ.get("PROXY_REMOVED") == "1",
  "removed_proxy_name": "xinao-researcher-egress-proxy",
  "removed_networks_observed": nets,
  "removed_networks_attempted": ["xinao_researcher_internal", "xinao_provider_egress_ext"],
  "dify_objects_touched": False,
  "provider_egress_runtime_verified_forced_false": True,
  "secrets_present": False,
  "note": "Receipt claims only observed removals; absent objects are not reported as removed.",
}
(root / "cleanup_receipt.v1.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n", encoding="utf-8")
posture = root / "current_posture.v1.json"
if posture.exists():
    data = json.loads(posture.read_text(encoding="utf-8"))
    data["lifecycle_state"] = "ABSENT"
    data["provider_egress_runtime_verified"] = False
    posture.write_text(json.dumps(data, indent=2, sort_keys=True)+"\n", encoding="utf-8")
print(json.dumps({"status":"CLEANED","provider_egress_runtime_verified":False,"proxy_removed_observed":receipt["proxy_removed_observed"],"removed_networks_observed":nets}, sort_keys=True))
'
