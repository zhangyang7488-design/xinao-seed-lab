#!/usr/bin/env bash
# Owner-only cleanup of XINAO researcher egress objects. Never touches Dify.
set -euo pipefail
export STATE_ROOT="${XINAO_EGRESS_STATE_ROOT:-D:/XINAO_RESEARCH_RUNTIME/state/xinao_skill/researcher_container/egress}"

docker ps -aq --filter "label=io.xinao.researcher.chain=dedicated-xinao-science" | while read -r id; do
  name="$(docker inspect -f '{{.Name}}' "$id" 2>/dev/null || true)"
  case "$name" in
    /xinao-researcher-*) docker rm -f "$id" >/dev/null || true ;;
  esac
done

docker rm -f xinao-researcher-egress-proxy >/dev/null 2>&1 || true
docker network rm xinao_researcher_internal >/dev/null 2>&1 || true
docker network rm xinao_provider_egress_ext >/dev/null 2>&1 || true

for name in ssrf_proxy ssrf_proxy_network; do
  if docker inspect "$name" >/dev/null 2>&1; then
    echo "left Dify object untouched: $name"
  fi
done

mkdir -p "$STATE_ROOT"
python3 -c '
import json, os
from pathlib import Path
from datetime import datetime, timezone
root = Path(os.environ["STATE_ROOT"])
receipt = {
  "schema_version": "xinao.provider_egress_cleanup_receipt.v1",
  "cleaned_at": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
  "removed_proxy_name": "xinao-researcher-egress-proxy",
  "removed_networks": ["xinao_researcher_internal", "xinao_provider_egress_ext"],
  "dify_objects_touched": False,
  "provider_egress_runtime_verified_forced_false": True,
  "secrets_present": False,
}
(root / "cleanup_receipt.v1.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n", encoding="utf-8")
posture = root / "current_posture.v1.json"
if posture.exists():
    data = json.loads(posture.read_text(encoding="utf-8"))
    data["lifecycle_state"] = "ABSENT"
    data["provider_egress_runtime_verified"] = False
    posture.write_text(json.dumps(data, indent=2, sort_keys=True)+"\n", encoding="utf-8")
print(json.dumps({"status":"CLEANED","provider_egress_runtime_verified":False}, sort_keys=True))
'
