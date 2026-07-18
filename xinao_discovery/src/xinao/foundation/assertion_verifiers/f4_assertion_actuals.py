"""Fresh, expectation-free F4 assertion actuals recomputation."""

from __future__ import annotations

import hashlib as _hashlib
import json as _json
import re as _re
from collections.abc import Mapping as _Mapping
from collections.abc import Sequence as _Sequence
from pathlib import Path as _Path
from typing import Any as _Any

_BLOCK_ID = "F4_research_factory"
_PROTOCOL_VERSION = "xinao.assertion_bundle_protocol.v2"
_ARTIFACT_TYPES = frozenset(
    {
        "TypedHandoffSchemaVersion",
        "EvidenceSchemaVersion",
        "ValidationCourtInterfaceVersion",
        "ResearchWorkItemSchemaVersion",
        "DynamicCapacityPolicyVersion",
        "DedupPolicyVersion",
        "DeterministicFanInPolicyVersion",
        "ResearchFactoryCanaryReport",
    }
)
_CURRENT_REQUIRED_TYPES = frozenset(_ARTIFACT_TYPES - {"ResearchFactoryCanaryReport"})
_SHA256_RE = _re.compile(r"^[0-9a-f]{64}$")


class _F4AssertionActualsError(ValueError):
    """Raised when the fresh F4 actuals chain is incomplete or contradictory."""


class _F4PathBoundary:
    """Snapshot-aware path checks without expanding the canonical callable surface."""

    @staticmethod
    def bound_file(value: object, label: str) -> _Path:
        from xinao.foundation import f4_current_evidence_verifier as _f4

        if not isinstance(value, _Mapping):
            raise _F4AssertionActualsError(f"{label} must be an object")
        ref = dict(value)
        if not all(isinstance(key, str) and key for key in ref):
            raise _F4AssertionActualsError(f"{label} keys must be non-empty text")
        if not {"path", "sha256", "size_bytes"} <= set(ref):
            raise _F4AssertionActualsError(f"{label} is not a complete file reference")
        if not isinstance(ref["path"], str) or not ref["path"]:
            raise _F4AssertionActualsError(f"{label}.path is invalid")
        if not isinstance(ref["sha256"], str) or not _SHA256_RE.fullmatch(ref["sha256"]):
            raise _F4AssertionActualsError(f"{label}.sha256 is invalid")
        if not isinstance(ref["size_bytes"], int) or ref["size_bytes"] < 0:
            raise _F4AssertionActualsError(f"{label}.size_bytes is invalid")
        try:
            path = _f4.readable_path(ref["path"], expect="file")
            raw = path.read_bytes()
        except (OSError, RuntimeError, ValueError) as exc:
            raise _F4AssertionActualsError(f"{label} does not exist: {ref['path']}") from exc
        if len(raw) != ref["size_bytes"]:
            raise _F4AssertionActualsError(f"{label} size binding drifted")
        if _hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise _F4AssertionActualsError(f"{label} hash binding drifted")
        return path

    @staticmethod
    def require_d_runtime(path: _Path, label: str) -> None:
        from xinao.foundation import f4_current_evidence_verifier as _f4

        if not _f4._inside(path, _f4.D_RUNTIME_ROOT):
            raise _F4AssertionActualsError(f"{label} is outside D runtime: {path}")

    @staticmethod
    def normalize_pretty_json_bytes(raw: bytes, label: str) -> bytes:
        """Normalize only the host newline convention for exact pretty JSON checks."""

        without_crlf = raw.replace(b"\r\n", b"\n")
        if b"\r" in without_crlf:
            raise _F4AssertionActualsError(f"{label} contains an unsupported carriage return")
        if b"\r\n" in raw and b"\n" in raw.replace(b"\r\n", b""):
            raise _F4AssertionActualsError(f"{label} contains mixed newline conventions")
        return without_crlf


class _F4RunProjection:
    """Semantic runs-v1 projection without expanding the callable registry."""

    @staticmethod
    def path_neutral_fresh_runs(value: object) -> dict[str, _Any]:
        """Project runs-v1 without treating physical launch paths as facts."""

        from xinao.foundation import f4_current_evidence_verifier as _f4

        if not isinstance(value, _Mapping):
            raise _F4AssertionActualsError("fresh verifier runs must be an object")
        record = dict(value)
        expected_top = {
            "schema_version",
            "python_executable",
            "run_count",
            "runs",
            "fresh_exact_content_equals_bound_count",
            "source_report_boolean_trust_count",
            "content_sha256",
        }
        raw_runs = record.get("runs")
        if (
            set(record) != expected_top
            or record.get("schema_version") != _f4.RUNS_SCHEMA
            or not isinstance(record.get("python_executable"), str)
            or not record.get("python_executable")
            or not isinstance(raw_runs, _Sequence)
            or isinstance(raw_runs, (str, bytes, bytearray))
            or record.get("run_count") != len(raw_runs)
            or record.get("fresh_exact_content_equals_bound_count") != len(raw_runs)
            or record.get("source_report_boolean_trust_count") != 0
        ):
            raise _F4AssertionActualsError("fresh verifier runs top-level shape drifted")
        expected_row = {
            "label",
            "argv",
            "shell",
            "source_pack_ref",
            "source_manifest_sha256",
            "bound_verification_ref",
            "bound_verification_file_sha256",
            "fresh_verification_file_sha256",
            "content_sha256",
            "assertion_count",
            "verifier_source_sha256",
        }
        projected: list[dict[str, _Any]] = []
        for raw in raw_runs:
            if not isinstance(raw, _Mapping):
                raise _F4AssertionActualsError("fresh verifier run row is invalid")
            row = dict(raw)
            argv = row.get("argv")
            source_spec = _f4.SOURCE_SPECS.get(row.get("label"))
            authority_script = (
                _Path(str(source_spec["script"]))
                if isinstance(source_spec, _Mapping) and source_spec.get("script")
                else None
            )
            sha_fields = (
                "source_manifest_sha256",
                "bound_verification_file_sha256",
                "fresh_verification_file_sha256",
                "content_sha256",
                "verifier_source_sha256",
            )
            if (
                set(row) != expected_row
                or not isinstance(argv, _Sequence)
                or isinstance(argv, (str, bytes, bytearray))
                or len(argv) != 7
                or not all(isinstance(item, str) and item for item in argv)
                or argv[0] != record["python_executable"]
                or list(argv[1::2]) != ["-I", "--pack", "--output-dir"]
                or argv[6] != "<ephemeral-output-dir>"
                or row.get("shell") is not False
                or not _f4._same_path(argv[4], row.get("source_pack_ref"))
                or authority_script is None
                or str(argv[2]).replace("\\", "/").rsplit("/", 1)[-1]
                != str(authority_script).replace("\\", "/").rsplit("/", 1)[-1]
                or _f4.file_sha256(authority_script) != row.get("verifier_source_sha256")
                or any(
                    not isinstance(row.get(field), str) or _SHA256_RE.fullmatch(row[field]) is None
                    for field in sha_fields
                )
                or not isinstance(row.get("assertion_count"), int)
                or isinstance(row.get("assertion_count"), bool)
                or row["assertion_count"] < 1
            ):
                raise _F4AssertionActualsError("fresh verifier run command binding drifted")
            projected.append(
                {
                    "label": row["label"],
                    "source_pack_ref": _f4.retained_path(row["source_pack_ref"]),
                    "source_manifest_sha256": row["source_manifest_sha256"],
                    "bound_verification_ref": _f4.retained_path(row["bound_verification_ref"]),
                    "bound_verification_file_sha256": row["bound_verification_file_sha256"],
                    "content_sha256": row["content_sha256"],
                    "assertion_count": row["assertion_count"],
                    "verifier_source_sha256": row["verifier_source_sha256"],
                    "command_shape": [
                        "python",
                        "-I",
                        "sha256-bound-verifier",
                        "--pack",
                        "retained-source-pack",
                        "--output-dir",
                        "<ephemeral-output-dir>",
                    ],
                }
            )
        return {
            "schema_version": record["schema_version"],
            "run_count": record["run_count"],
            "runs": projected,
            "fresh_exact_content_equals_bound_count": record[
                "fresh_exact_content_equals_bound_count"
            ],
            "source_report_boolean_trust_count": record["source_report_boolean_trust_count"],
        }


def build_assertion_actuals_v1(request: _Mapping[str, _Any]) -> dict[str, bool]:
    """Freshly reconstruct F4 evidence and return only requested predicate actuals."""

    from xinao.foundation import f4_current_evidence_verifier as _f4

    _AssertionActualsError = _F4AssertionActualsError
    _bound_file = _F4PathBoundary.bound_file
    _require_d_runtime = _F4PathBoundary.require_d_runtime

    def _require(condition: bool, message: str) -> None:
        if not condition:
            raise _AssertionActualsError(message)

    def _mapping(value: object, label: str) -> dict[str, _Any]:
        _require(isinstance(value, _Mapping), f"{label} must be an object")
        result = dict(value)
        _require(
            all(isinstance(key, str) and key for key in result),
            f"{label} keys must be non-empty text",
        )
        return result

    def _sha256_bytes(value: bytes) -> str:
        return _hashlib.sha256(value).hexdigest()

    def _load_json(path: _Path, label: str) -> dict[str, _Any]:
        try:
            value = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, _json.JSONDecodeError) as exc:
            raise _AssertionActualsError(f"{label} must be readable JSON: {path}") from exc
        return _mapping(value, label)

    def _canonical_content(value: object) -> str:
        return _f4.canonical_sha256(value)

    def _generic_content_address(value: dict[str, _Any], label: str) -> str:
        content_hash = value.get("content_sha256")
        _require(
            isinstance(content_hash, str) and _SHA256_RE.fullmatch(content_hash),
            f"{label}.content_sha256 is invalid",
        )
        core = dict(value)
        core.pop("content_sha256", None)
        _require(_canonical_content(core) == content_hash, f"{label} content identity drifted")
        return content_hash

    def _canary_content_address(value: dict[str, _Any]) -> str:
        content_hash = value.get("content_sha256")
        version_id = value.get("version_id")
        _require(
            isinstance(content_hash, str) and _SHA256_RE.fullmatch(content_hash),
            "canary content_sha256 is invalid",
        )
        _require(
            version_id == f"ResearchFactoryCanaryReport@{content_hash[:16]}",
            "canary version identity drifted",
        )
        core = dict(value)
        core.pop("content_sha256", None)
        core.pop("version_id", None)
        _require(_canonical_content(core) == content_hash, "canary content identity drifted")
        return content_hash

    def _render_pretty(value: dict[str, _Any]) -> bytes:
        return _f4._pretty_json_bytes(value)

    def _normalized_checker(value: dict[str, _Any], label: str) -> dict[str, _Any]:
        _generic_content_address(value, label)
        _require(
            value.get("schema_version") == _f4.CHECKER_SCHEMA
            and value.get("status") == "VERIFIED"
            and value.get("check_count") == 17
            and value.get("verified_check_count") == 17
            and value.get("pytest_loaded") is False,
            f"{label} is not the package-owned 17-check result",
        )
        return value

    try:
        source = _mapping(request, "request")
        _require(
            source.get("schema_version") == "xinao.assertion_request.v2",
            "request schema is invalid",
        )
        _require(
            source.get("protocol_version") == _PROTOCOL_VERSION,
            "request protocol is invalid",
        )
        _require(source.get("block_id") == _BLOCK_ID, "request block_id is invalid")
        _require(
            "expected" not in source and "required_assertions" not in source,
            "request must not contain blueprint expectations",
        )

        raw_assertion_ids = source.get("assertion_ids")
        _require(
            isinstance(raw_assertion_ids, _Sequence)
            and not isinstance(raw_assertion_ids, (str, bytes, bytearray))
            and raw_assertion_ids
            and all(isinstance(item, str) and item for item in raw_assertion_ids),
            "request assertion_ids is invalid",
        )
        assertion_ids = tuple(raw_assertion_ids)
        _require(
            list(assertion_ids) == sorted(set(assertion_ids)),
            "request assertion_ids must be sorted and unique",
        )
        _require(
            set(assertion_ids) <= set(_f4.ASSERTION_IDS),
            "request contains an unknown F4 assertion ID",
        )

        input_hashes = _mapping(source.get("input_hashes"), "request.input_hashes")
        _require(input_hashes, "request.input_hashes is empty")
        _require(
            all(
                isinstance(value, str) and _SHA256_RE.fullmatch(value)
                for value in input_hashes.values()
            ),
            "request.input_hashes contains an invalid SHA-256",
        )
        compiler_code_hash = source.get("compiler_code_sha256")
        compiler_config_hash = source.get("compiler_config_sha256")
        _require(
            isinstance(compiler_code_hash, str) and _SHA256_RE.fullmatch(compiler_code_hash),
            "request.compiler_code_sha256 is invalid",
        )
        _require(
            isinstance(compiler_config_hash, str) and _SHA256_RE.fullmatch(compiler_config_hash),
            "request.compiler_config_sha256 is invalid",
        )

        artifacts = _mapping(source.get("artifacts"), "request.artifacts")
        _require(
            set(artifacts) == _ARTIFACT_TYPES,
            "request must contain the exact eight F4 artifact types",
        )
        payloads: dict[str, dict[str, _Any]] = {}
        source_paths: dict[str, _Path] = {}
        for artifact_type in sorted(_ARTIFACT_TYPES):
            artifact = _mapping(artifacts[artifact_type], f"artifact[{artifact_type}]")
            _require(
                set(artifact) == {"staged_envelope", "staged_envelope_content_sha256"},
                f"artifact[{artifact_type}] envelope keys drifted",
            )
            envelope = _mapping(
                artifact.get("staged_envelope"),
                f"artifact[{artifact_type}].staged_envelope",
            )
            expected_envelope_keys = {
                "artifact_type",
                "version",
                "input_hashes",
                "code_hash",
                "config_hash",
                "source_ref",
                "payload",
                "payload_sha256",
            }
            _require(
                set(envelope) == expected_envelope_keys,
                f"artifact[{artifact_type}] staged envelope keys drifted",
            )
            _require(
                envelope.get("artifact_type") == artifact_type,
                f"artifact[{artifact_type}] type identity drifted",
            )
            _require(
                isinstance(envelope.get("version"), str) and envelope["version"],
                f"artifact[{artifact_type}] version is invalid",
            )
            _require(
                envelope.get("input_hashes") == input_hashes
                and envelope.get("code_hash") == compiler_code_hash
                and envelope.get("config_hash") == compiler_config_hash,
                f"artifact[{artifact_type}] request bindings drifted",
            )
            payload = _mapping(envelope.get("payload"), f"artifact[{artifact_type}].payload")
            _require(
                envelope.get("payload_sha256") == _canonical_content(payload),
                f"artifact[{artifact_type}] payload identity drifted",
            )
            _require(
                artifact.get("staged_envelope_content_sha256") == _canonical_content(envelope),
                f"artifact[{artifact_type}] envelope content identity drifted",
            )
            source_path = _bound_file(
                envelope.get("source_ref"),
                f"artifact[{artifact_type}].source_ref",
            )
            _require_d_runtime(source_path, f"artifact[{artifact_type}].source_ref")
            source_payload = _load_json(source_path, f"artifact source {artifact_type}")
            _require(
                source_payload == payload,
                f"artifact[{artifact_type}] payload differs from source bytes",
            )
            version = payload.get("version_id") or payload.get("schema_version")
            _require(
                envelope.get("version") == version,
                f"artifact[{artifact_type}] version differs from payload",
            )
            payloads[artifact_type] = payload
            source_paths[artifact_type] = source_path

        canary = payloads["ResearchFactoryCanaryReport"]
        _canary_content_address(canary)
        map_path = _bound_file(
            canary.get("f4_assertion_evidence_map"),
            "canary.f4_assertion_evidence_map",
        )
        _require_d_runtime(map_path, "canary.f4_assertion_evidence_map")
        retained_map = _load_json(map_path, "F4AssertionEvidenceMap")
        retained_map_hash = _generic_content_address(retained_map, "F4AssertionEvidenceMap")
        _require(
            retained_map.get("object_type") == "F4AssertionEvidenceMap",
            "canary map object type drifted",
        )
        _require(
            canary.get("f4_assertion_evidence_map_content_sha256") == retained_map_hash,
            "canary map content binding drifted",
        )

        current_source_pack = canary.get("current_source_pack_ref")
        _require(
            isinstance(current_source_pack, str) and current_source_pack,
            "canary current source pack ref is invalid",
        )
        current = _f4.verify_current_pack(_Path(current_source_pack))
        manifest_path = _bound_file(
            canary.get("current_source_manifest"),
            "canary.current_source_manifest",
        )
        _require_d_runtime(manifest_path, "canary.current_source_manifest")
        _require(
            manifest_path == current.manifest_path,
            "canary identifies another current-source manifest",
        )
        _require(
            _f4._same_path(retained_map.get("current_source_pack_ref"), current.root),
            "map current-source pack ref drifted",
        )
        for artifact_type in sorted(_CURRENT_REQUIRED_TYPES):
            current_payload = _load_json(
                current.required_paths[artifact_type],
                f"current payload {artifact_type}",
            )
            _require(
                payloads[artifact_type] == current_payload,
                f"request artifact is not the current compiler payload: {artifact_type}",
            )

        runs_path = _bound_file(retained_map.get("fresh_verifier_runs"), "map.fresh_runs")
        checker_path = _bound_file(retained_map.get("targeted_checker"), "map.targeted_checker")
        audit_path = _bound_file(
            retained_map.get("evidence_plane_audit"),
            "map.evidence_plane_audit",
        )
        for bound_path, label in (
            (runs_path, "map.fresh_runs"),
            (checker_path, "map.targeted_checker"),
            (audit_path, "map.evidence_plane_audit"),
        ):
            _require_d_runtime(bound_path, label)
        retained_runs = _load_json(runs_path, "retained fresh verifier runs")
        retained_checker = _load_json(checker_path, "retained targeted checker")
        retained_audit = _load_json(audit_path, "retained evidence plane audit")
        _generic_content_address(retained_runs, "retained fresh verifier runs")
        _generic_content_address(retained_audit, "retained evidence plane audit")

        from xinao.foundation.assertion_verifier_registry import (
            canonical_f4_workflow_python_executable,
        )

        fresh = _f4.rerun_bound_verifiers(
            current,
            python_executable=canonical_f4_workflow_python_executable(),
        )
        fresh_checker = _f4.run_targeted_checker()
        fresh_audit = _f4.audit_evidence_plane(current, fresh)
        fresh_runs = _f4._fresh_runs_record(fresh)
        _require(
            _F4RunProjection.path_neutral_fresh_runs(retained_runs)
            == _F4RunProjection.path_neutral_fresh_runs(fresh_runs),
            "retained three-source fresh-run facts differ from current rerun",
        )
        _require(
            retained_audit == fresh_audit,
            "retained evidence-plane audit differs from current audit",
        )
        _require(
            _normalized_checker(retained_checker, "retained targeted checker")
            == _normalized_checker(fresh_checker, "fresh targeted checker"),
            "retained 17-node checker facts differ from current rerun",
        )

        rebuilt_map = _f4.build_assertion_evidence_map(
            current,
            fresh,
            runs_path=runs_path,
            checker_path=checker_path,
            audit_path=audit_path,
        )
        _require(rebuilt_map == retained_map, "retained F4 assertion map differs from rebuild")
        _require(
            _F4PathBoundary.normalize_pretty_json_bytes(
                map_path.read_bytes(),
                "retained F4 assertion map",
            )
            == _render_pretty(rebuilt_map),
            "retained F4 assertion map bytes differ from rebuild",
        )
        rebuilt_canary = _f4.build_canary_report(current, rebuilt_map, map_path, fresh)
        _require(rebuilt_canary == canary, "retained F4 canary differs from rebuild")
        _require(
            _F4PathBoundary.normalize_pretty_json_bytes(
                source_paths["ResearchFactoryCanaryReport"].read_bytes(),
                "retained F4 canary",
            )
            == _render_pretty(rebuilt_canary),
            "retained F4 canary bytes differ from rebuild",
        )

        rebuilt_assertions = _mapping(rebuilt_map.get("assertions"), "rebuilt assertions")
        actuals: dict[str, bool] = {}
        for assertion_id in assertion_ids:
            item = _mapping(rebuilt_assertions.get(assertion_id), f"assertion[{assertion_id}]")
            content_hash = _generic_content_address(item, f"assertion[{assertion_id}]")
            _require(
                item.get("assertion_id") == assertion_id
                and item.get("verification_state") == "VERIFIED"
                and isinstance(item.get("evidence_refs"), list)
                and bool(item["evidence_refs"])
                and isinstance(content_hash, str),
                f"rebuilt assertion is not independently verified: {assertion_id}",
            )
            actuals[assertion_id] = True
        _require(set(actuals) == set(assertion_ids), "actual assertion inventory drifted")
        return {assertion_id: actuals[assertion_id] for assertion_id in assertion_ids}
    except _AssertionActualsError:
        raise
    except Exception as exc:
        raise _AssertionActualsError(f"fresh F4 assertion reconstruction failed: {exc}") from exc


__all__ = ["build_assertion_actuals_v1"]
