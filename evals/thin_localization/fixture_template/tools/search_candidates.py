from __future__ import annotations

import json
import shutil
import subprocess

CANDIDATES = (
    {
        "candidate_id": "python/json.tool",
        "source_kind": "official",
        "source_url": "https://github.com/python/cpython",
        "executable": "python",
        "version_args": ["--version"],
        "args": ["-m", "json.tool", "--sort-keys", "--compact"],
        "fit": "mature standard-library CLI; exact current JSON normalization atoms",
    },
    {
        "candidate_id": "jqlang/jq",
        "source_kind": "community",
        "source_url": "https://github.com/jqlang/jq",
        "executable": "jq",
        "version_args": ["--version"],
        "args": ["--sort-keys", "--compact-output", "."],
        "fit": "mature dedicated JSON CLI; exact current atoms with no local wrapper",
    },
    {
        "candidate_id": "mikefarah/yq",
        "source_kind": "personal",
        "source_url": "https://github.com/mikefarah/yq",
        "executable": "yq",
        "version_args": ["--version"],
        "args": ["-o=json", "-I=0", "sort_keys(..)"],
        "fit": "individual-maintained public CLI; exact current atoms and broader YAML support",
    },
)


def probe(candidate: dict[str, object]) -> dict[str, object]:
    executable = str(candidate["executable"])
    resolved = shutil.which(executable)
    record = dict(candidate)
    record["available"] = resolved is not None
    record["resolved_executable"] = resolved
    record["observed_version"] = None
    if resolved:
        completed = subprocess.run(
            [resolved, *candidate["version_args"]],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        record["observed_version"] = (completed.stdout or completed.stderr).strip()
    return record


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "schema_version": "xinao.external_candidate_probe.v1",
                "probe_nonce": "THIN-SEARCH-OBSERVED-6C210A",
                "candidates": [probe(candidate) for candidate in CANDIDATES],
            },
            sort_keys=True,
        )
    )
