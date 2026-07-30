#!/usr/bin/env bash
# Owner-only: resolve ubuntu/squid to immutable digest + image id. No credentials.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN_PATH="${1:-$ROOT/image-pin.v1.json}"
REPO="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["image_repository"])' "$PIN_PATH")"
TAG="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("image_tag_observational") or "latest")' "$PIN_PATH")"
REF="${REPO}:${TAG}"
echo "Pulling observational tag ${REF} (not authority)..."
docker pull "$REF"
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$REF")"
DIGEST_REF="$(docker image inspect --format '{{index .RepoDigests 0}}' "$REF" 2>/dev/null || true)"
if [[ -z "${DIGEST_REF}" || "${DIGEST_REF}" == "<no value>" ]]; then
  echo "RepoDigests missing; sealing image_id only is acceptable if digest unavailable."
  DIGEST_REF=""
fi
python3 -c '
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
image_id = sys.argv[2]
digest = sys.argv[3] or None
pin = json.loads(path.read_text(encoding="utf-8"))
pin["image_id"] = image_id
pin["image_digest"] = digest
pin["floating_tag_as_authority"] = False
pin["authority"] = "immutable_digest_or_image_id_only"
path.write_text(json.dumps(pin, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"status":"PINNED","image_id":pin["image_id"],"image_digest":pin["image_digest"]}, sort_keys=True))
' "$PIN_PATH" "$IMAGE_ID" "$DIGEST_REF"
