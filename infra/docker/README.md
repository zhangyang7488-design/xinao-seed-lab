# Docker capacity defaults

`daemon.capacity.json` is the secret-free projection of the intended Docker
Desktop Linux-engine defaults on this machine. The active user configuration is
`C:\Users\xx363\.docker\daemon.json`.

At the pre-reboot closure on 2026-07-17, the file projection was written but
the running engine still reported `json-file`. The `local` default is therefore
pending a Docker/Windows restart and fresh-runtime verification; this document
or a valid JSON file is not activation evidence.

## Intended behavior

- BuildKit garbage collection stays enabled with 20 GB of retained build
  cache. This bounds future cache growth without deleting every reusable layer.
- Newly created containers use Docker's `local` logging driver with three
  10 MiB rotated files. Existing containers keep their current logging driver
  until they are recreated for their own reason; capacity maintenance must not
  force an unrelated fleet-wide recreation.
- Image cleanup is identity based. A tagless or unused image is not an orphan
  until current Compose files, frozen F4 inputs, rollback manifests and
  on-demand capability contracts have all been checked.
- The Docker Desktop VHDX is measured separately from logical image/cache
  reclamation. After Docker is stopped cleanly, Desktop's managed reclaim is
  preferred. A detached `compact vdisk` is a maintenance fallback, never an
  online cleanup command.
- Removing an image changes Docker's logical catalog. It does not prove that
  the sparse VHDX or Windows volume physically shrank. Measure both after the
  engine stops and restarts before claiming host-space recovery.

## Rejected shortcuts

- Do not run `docker system prune -a --volumes` on this machine. It cannot
  distinguish current, frozen, on-demand and rollback identities.
- Do not set BuildKit's retained space to zero. Rebuilding all pinned images
  wastes time and network without improving steady-state capacity control.
- Do not claim host space was recovered from `docker image rm` until the VHDX
  file and the Windows volume are measured after managed reclaim.

After the next Docker restart, verify `docker info --format '{{.LoggingDriver}}'`
returns `local` and `docker buildx inspect` still reports the configured 20 GB
GC policy. Rollback is the previous valid file containing only the builder GC
block and `"experimental": false`, followed by one Docker Desktop restart.

References: Docker logging configuration and the local logging driver are
documented at https://docs.docker.com/engine/logging/configure/ and
https://docs.docker.com/engine/logging/drivers/local/. Build cache GC is
documented at https://docs.docker.com/build/cache/garbage-collection/.
