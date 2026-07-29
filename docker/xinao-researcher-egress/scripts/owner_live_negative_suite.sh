#!/usr/bin/env bash
# Owner-only live negative suite (N1-N17 spirit). Requires provisioned topology.
# Does not read credentials. Does not flip verified=true.
set -euo pipefail
NETWORK="${XINAO_EGRESS_INTERNAL_NETWORK:-xinao_researcher_internal}"
PROXY_URL="${XINAO_EGRESS_PROXY_URL:-http://xinao-researcher-egress-proxy:3128}"
CLIENT_IMAGE="${XINAO_EGRESS_CLIENT_IMAGE:-busybox:1.36}"
RESULTS="${XINAO_EGRESS_NEGATIVE_RECEIPT:-./negative_suite_receipt.v1.json}"

pass=0
fail=0
record() {
  local id="$1" expect="$2" got="$3" ok="$4"
  echo "$id expect=$expect got=$got ok=$ok"
  if [[ "$ok" == "1" ]]; then pass=$((pass+1)); else fail=$((fail+1)); fi
}

run_proxy() {
  local target="$1"
  docker run --rm --network "$NETWORK" \
    -e "http_proxy=$PROXY_URL" -e "https_proxy=$PROXY_URL" \
    -e "HTTP_PROXY=$PROXY_URL" -e "HTTPS_PROXY=$PROXY_URL" \
    "$CLIENT_IMAGE" wget -S -O /dev/null -T 8 "$target" 2>&1 || true
}

run_direct() {
  local target="$1"
  docker run --rm --network "$NETWORK" \
    -e http_proxy= -e https_proxy= -e HTTP_PROXY= -e HTTPS_PROXY= \
    "$CLIENT_IMAGE" wget -S -O /dev/null -T 8 "$target" 2>&1 || true
}

out="$(run_direct "https://example.com/")"
if echo "$out" | grep -qiE 'bad address|can.t connect|timed out|network is unreachable|no route|wget:'; then
  record N1 no_route_or_timeout fail_closed 1
else
  record N1 no_route_or_timeout unexpected_success 0
fi

out="$(run_proxy "https://example.com/")"
if echo "$out" | grep -qE '403|denied|Forbidden'; then
  record N3 proxy_arbitrary_domain 403 1
else
  record N3 proxy_arbitrary_domain not_denied 0
fi

out="$(run_proxy "https://10.0.0.1/")"
if echo "$out" | grep -qE '403|denied|Forbidden|can.t connect'; then
  record N4 proxy_rfc1918 denied 1
else
  record N4 proxy_rfc1918 allowed 0
fi

out="$(run_proxy "https://169.254.169.254/")"
if echo "$out" | grep -qE '403|denied|Forbidden|can.t connect'; then
  record N5 metadata denied 1
else
  record N5 metadata allowed 0
fi

out="$(run_proxy "https://127.0.0.1/")"
if echo "$out" | grep -qE '403|denied|Forbidden|can.t connect'; then
  record N6 loopback denied 1
else
  record N6 loopback allowed 0
fi

out="$(run_proxy "http://example.com/")"
if echo "$out" | grep -qE '403|denied|Forbidden|bad port'; then
  record N8 cleartext_80 denied 1
else
  record N8 cleartext_80 allowed 0
fi

# N7: non-443 CONNECT-style HTTPS URL with explicit alternate port (busybox wget path).
out="$(run_proxy "https://example.com:8443/")"
if echo "$out" | grep -qE '403|denied|Forbidden|bad port|can.t connect'; then
  record N7 connect_non_443 denied 1
else
  record N7 connect_non_443 allowed 0
fi

# N17: raw IP literal via proxy (default deny).
out="$(run_proxy "https://1.1.1.1/")"
if echo "$out" | grep -qE '403|denied|Forbidden|can.t connect'; then
  record N17 ip_literal denied 1
else
  record N17 ip_literal allowed 0
fi

out="$(run_direct "https://example.com/")"
if echo "$out" | grep -qiE 'bad address|can.t connect|timed out|network is unreachable|no route|wget:'; then
  record N9 proxy_env_unset_internal_only no_external 1
else
  record N9 proxy_env_unset_internal_only leaked 0
fi

if docker inspect xinao-researcher-egress-proxy --format '{{json .NetworkSettings.Networks}}' | grep -q ssrf_proxy; then
  record N15 no_dify_attach unexpected 0
else
  record N15 no_dify_attach isolated 1
fi

export PASS_COUNT="$pass" FAIL_COUNT="$fail" RESULTS_PATH="$RESULTS"
python3 -c '
import json, os
from datetime import datetime, timezone
receipt = {
  "schema_version": "xinao.provider_egress_negative_suite_receipt.v1",
  "executed_at": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
  "pass_count": int(os.environ["PASS_COUNT"]),
  "fail_count": int(os.environ["FAIL_COUNT"]),
  "provider_egress_runtime_verified": False,
  "secrets_present": False,
  "note": "Partial automated probe set; Owner completes full N1-N17 including CONNECT non-443, DNS rebind, foreign membership.",
}
open(os.environ["RESULTS_PATH"], "w", encoding="utf-8").write(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
print(json.dumps(receipt, sort_keys=True))
raise SystemExit(0 if int(os.environ["FAIL_COUNT"]) == 0 else 1)
'
