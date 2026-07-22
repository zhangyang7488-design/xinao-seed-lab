"""SealedTruthVault: synthetic truth only; unreadable to subject/Promptfoo processes.

Isolation is process-visible via filesystem capabilities:
- vault root is outside subject/public/promptfoo roots
- subject capability token is denied for vault reads
- evaluator capability token required for evaluator view
"""

from __future__ import annotations

import json
import os
import re
import stat
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .canonical import identity_from_fields, write_json
from . import SYNTHETIC_LABEL

SUBJECT_CAP = "CAP_SUBJECT_NO_VAULT"
EVALUATOR_CAP = "CAP_EVALUATOR_VAULT_READ"
CUSTODIAN_CAP = "CAP_VAULT_CUSTODIAN"
PRE_RECEIPT_TARGET_NAMES = (
    "sealed_truth.v1.json",
    "vault_meta.v1.json",
    ".subject_denied",
)
FINAL_TARGET_NAMES = PRE_RECEIPT_TARGET_NAMES + ("host_lockdown.v1.json",)

# Windows ERROR_ACCESS_DENIED / ERROR_SHARING_VIOLATION. winerror==5 or the
# host's real PermissionError errno==13 form can prove access denial; sharing
# violations and bare PermissionError injections do not.
WINERROR_ACCESS_DENIED = 5
WINERROR_SHARING_VIOLATION = 32

SUBJECT_FORBIDDEN_KEYS = frozenset(
    {
        "truth",
        "answer",
        "sealed_answer",
        "seed",
        "hidden_parameters",
        "parameters",
        "family_identity",
        "rejection_label",
        "scorer_features",
        "ground_truth",
        "answer_key",
        "scoring_rule",
        "vault_locator",
    }
)


class SealedTruthVault:
    def __init__(self, vault_root: str | Path) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.vault_root.mkdir(parents=True, exist_ok=True)
        self.truth_path = self.vault_root / "sealed_truth.v1.json"
        self.meta_path = self.vault_root / "vault_meta.v1.json"
        deny_marker = self.vault_root / ".subject_denied"
        existing_entries = list(self.vault_root.iterdir())
        if not existing_entries:
            write_json(
                self.truth_path,
                {
                    "schema_version": "xinao.g4.hidden_capability_seam.sealed_truth_vault.v1",
                    "synthetic_only": True,
                    "label": SYNTHETIC_LABEL,
                    "items": {},
                    "not_real_hidden_suite": True,
                    "authority": False,
                },
            )
            write_json(
                self.meta_path,
                {
                    "schema_version": "xinao.g4.hidden_capability_seam.vault_meta.v1",
                    "vault_root": str(self.vault_root),
                    "subject_cap_allowed": False,
                    "evaluator_cap": EVALUATOR_CAP,
                    "custodian_cap": CUSTODIAN_CAP,
                    "synthetic_only": True,
                    "authority": False,
                },
            )
            deny_marker.write_text("SUBJECT_READ_DENIED\n", encoding="utf-8")

    def locator_for_custodian(self, *, capability: str) -> dict[str, Any]:
        if capability != CUSTODIAN_CAP:
            return {"ok": False, "reason": "vault_locator_denied", "capability": capability}
        return {
            "ok": True,
            "vault_locator": str(self.vault_root),
            "capability": capability,
            "note": "never embed in public manifest/config/result",
        }

    def deposit_synthetic(
        self,
        *,
        public_case_id: str,
        public_prompt: str,
        truth: Any,
        scoring_rule_private: dict[str, Any],
        family_slot: str,
        schedule_class: str,
        capability: str = CUSTODIAN_CAP,
    ) -> dict[str, Any]:
        if capability != CUSTODIAN_CAP:
            return {"ok": False, "reason": "deposit_denied"}
        data = self._read_truth_unlocked(expected_receipt=False)
        commitment_inputs = {
            "public_case_id": public_case_id,
            "public_prompt": public_prompt,
            "truth": truth,
            "scoring_rule_private": scoring_rule_private,
            "family_slot": family_slot,
            "schedule_class": schedule_class,
            "label": SYNTHETIC_LABEL,
        }
        commitment = identity_from_fields("SealedParameterCommitment", commitment_inputs)
        # Public commitment strips secret inputs
        public_commitment = {
            "schema_version": "xinao.g4.hidden_capability_seam.sealed_parameter_commitment.v1",
            "public_case_id": public_case_id,
            "commitment_sha256": commitment["identity_sha256"],
            "hash_profile": "canonical-json-v1+sha256",
            "synthetic_only": True,
            "label": SYNTHETIC_LABEL,
            "not_admission": True,
        }
        item = {
            "public_case_id": public_case_id,
            "public_prompt": public_prompt,
            "truth": truth,
            "scoring_rule_private": scoring_rule_private,
            "family_slot": family_slot,
            "schedule_class": schedule_class,
            "commitment_sha256": commitment["identity_sha256"],
            "commitment_inputs_sha256": commitment["identity_sha256"],
            "label": SYNTHETIC_LABEL,
            "synthetic": True,
        }
        data["items"][public_case_id] = item
        write_json(self.truth_path, data)
        return {"ok": True, "public_commitment": public_commitment, "item_id": public_case_id}

    def subject_read(self, *, capability: str, public_case_id: str) -> dict[str, Any]:
        """Subject/Promptfoo path: always deny vault truth."""
        denied = {
            "ok": False,
            "reason": "subject_vault_read_denied",
            "capability": capability,
            "public_case_id": public_case_id,
            "vault_readable": False,
            "audited": True,
        }
        if capability == SUBJECT_CAP or capability != EVALUATOR_CAP and capability != CUSTODIAN_CAP:
            return denied
        return denied

    def evaluator_view(self, *, capability: str, public_case_id: str) -> dict[str, Any]:
        if capability != EVALUATOR_CAP:
            return {
                "ok": False,
                "reason": "evaluator_capability_invalid",
                "capability": capability,
            }
        data = self._read_truth_unlocked(expected_receipt=False)
        item = data.get("items", {}).get(public_case_id)
        if item is None:
            return {"ok": False, "reason": "unknown_case", "public_case_id": public_case_id}
        return {
            "ok": True,
            "view": "evaluator",
            "public_case_id": public_case_id,
            "truth": item["truth"],
            "scoring_rule_private": item["scoring_rule_private"],
            "commitment_sha256": item["commitment_sha256"],
            "family_slot": item["family_slot"],
            "schedule_class": item["schedule_class"],
            "synthetic": True,
            "label": SYNTHETIC_LABEL,
            "real_capability_result": False,
            "not_admission": True,
        }

    def public_case_view(self, public_case_id: str) -> dict[str, Any]:
        data = self._read_truth_unlocked(expected_receipt=False)
        item = data.get("items", {}).get(public_case_id)
        if item is None:
            return {"ok": False, "reason": "unknown_case"}
        view = {
            "ok": True,
            "view": "public",
            "public_case_id": public_case_id,
            "public_prompt": item["public_prompt"],
            "commitment_sha256": item["commitment_sha256"],
            "schedule_class": item["schedule_class"],
            "synthetic": True,
            "label": SYNTHETIC_LABEL,
            "not_admission": True,
            "not_discovery": True,
            "not_rejection_evidence": True,
        }
        for k in SUBJECT_FORBIDDEN_KEYS:
            view.pop(k, None)
        return view

    def verify_commitment(
        self, public_case_id: str, claimed_commitment_sha256: str
    ) -> dict[str, Any]:
        data = self._read_truth_unlocked(expected_receipt=False)
        item = data.get("items", {}).get(public_case_id)
        if item is None:
            return {"ok": False, "reason": "unknown_case"}
        match = item["commitment_sha256"] == claimed_commitment_sha256
        return {
            "ok": match,
            "reason": None if match else "commitment_input_drift",
            "public_case_id": public_case_id,
        }

    def commitment_drift_check(
        self,
        *,
        public_case_id: str,
        mutated_truth: Any,
    ) -> dict[str, Any]:
        """Prove that changing truth changes commitment identity."""
        data = self._read_truth_unlocked(expected_receipt=False)
        item = data.get("items", {}).get(public_case_id)
        if item is None:
            return {"ok": False, "reason": "unknown_case"}
        original = item["commitment_sha256"]
        alt_inputs = {
            "public_case_id": public_case_id,
            "public_prompt": item["public_prompt"],
            "truth": mutated_truth,
            "scoring_rule_private": item["scoring_rule_private"],
            "family_slot": item["family_slot"],
            "schedule_class": item["schedule_class"],
            "label": SYNTHETIC_LABEL,
        }
        alt = identity_from_fields("SealedParameterCommitment", alt_inputs)
        drifted = alt["identity_sha256"] != original
        return {
            "ok": drifted,
            "original_commitment_sha256": original,
            "mutated_commitment_sha256": alt["identity_sha256"],
            "reason": None if drifted else "commitment_did_not_drift",
        }

    def assert_path_isolation(
        self,
        *,
        subject_root: str | Path,
        promptfoo_root: str | Path,
        evaluator_root: str | Path,
    ) -> dict[str, Any]:
        vr = self.vault_root
        sr = Path(subject_root).resolve()
        pr = Path(promptfoo_root).resolve()
        er = Path(evaluator_root).resolve()
        problems: list[str] = []
        for name, root in (("subject", sr), ("promptfoo", pr)):
            try:
                vr.relative_to(root)
                problems.append(f"vault_inside_{name}_root")
            except ValueError:
                pass
            # subject must not have env pointing at vault
        # evaluator root must be distinct from subject/promptfoo
        if er == sr or er == pr:
            problems.append("evaluator_root_not_separate")
        if vr == sr or vr == pr:
            problems.append("vault_colocated_with_subject_or_promptfoo")
        # The marker is created only during pristine Vault initialization.  A
        # partial existing Vault must never be silently reconstructed here.
        deny_marker = vr / ".subject_denied"
        try:
            marker_ok = (
                deny_marker.is_file()
                and not deny_marker.is_symlink()
                and deny_marker.read_text(encoding="utf-8") == "SUBJECT_READ_DENIED\n"
            )
        except OSError:
            marker_ok = False
        if not marker_ok:
            problems.append("subject_deny_marker_missing_or_invalid")
        return {
            "ok": len(problems) == 0,
            "problems": problems,
            "vault_root": str(vr),
            "subject_root": str(sr),
            "promptfoo_root": str(pr),
            "evaluator_root": str(er),
            "subject_cap": SUBJECT_CAP,
            "evaluator_cap": EVALUATOR_CAP,
        }

    def status(self, *, expected_receipt: bool) -> dict[str, Any]:
        data = self._read_truth_unlocked(expected_receipt=expected_receipt)
        return {
            "schema_version": "xinao.g4.hidden_capability_seam.sealed_truth_vault.v1",
            "object": "SealedTruthVault",
            "item_count": len(data.get("items", {})),
            "synthetic_only": True,
            "vault_root": str(self.vault_root),
            "real_hidden_present": False,
            "authority": False,
            "label": SYNTHETIC_LABEL,
        }

    def _expected_vault_targets(self, *, expected_receipt: bool) -> list[Path]:
        names = FINAL_TARGET_NAMES if expected_receipt else PRE_RECEIPT_TARGET_NAMES
        return [self.vault_root / name for name in names]

    @staticmethod
    def _normalized_target_identity(path: Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def _list_vault_entries(self) -> list[Path]:
        """One testable boundary for complete immediate-child enumeration."""
        return list(self.vault_root.iterdir())

    def _exact_controlled_vault_targets(
        self, *, expected_receipt: bool
    ) -> tuple[list[Path], dict[str, Any]]:
        """Require the exact phase-specific regular-file set with no omissions."""
        expected = self._expected_vault_targets(expected_receipt=expected_receipt)
        expected_map = {self._normalized_target_identity(path): path for path in expected}
        problems: list[str] = []
        observed: list[Path] = []
        try:
            observed = self._list_vault_entries()
        except OSError as exc:
            problems.append(f"vault_enumeration_failed:{type(exc).__name__}")

        observed_map: dict[str, Path] = {}
        for path in observed:
            key = self._normalized_target_identity(path)
            if key in observed_map:
                problems.append(f"duplicate_normalized_target:{path.name}")
            observed_map[key] = path
            try:
                info = path.lstat()
                attributes = int(getattr(info, "st_file_attributes", 0))
                if stat.S_ISLNK(info.st_mode) or attributes & 0x400:
                    problems.append(f"target_reparse_or_symlink:{path.name}")
                elif not stat.S_ISREG(info.st_mode):
                    problems.append(f"target_not_regular_file:{path.name}")
            except OSError as exc:
                problems.append(f"target_discovery_failed:{path.name}:{type(exc).__name__}")

        missing = sorted(path.name for key, path in expected_map.items() if key not in observed_map)
        extra = sorted(path.name for key, path in observed_map.items() if key not in expected_map)
        problems.extend(f"missing_expected_target:{name}" for name in missing)
        problems.extend(f"unexpected_vault_target:{name}" for name in extra)
        exact = bool(
            not problems
            and len(expected_map) == len(expected)
            and len(observed_map) == len(expected_map)
            and set(observed_map) == set(expected_map)
        )
        evidence = {
            "ok": exact,
            "expected_receipt": expected_receipt,
            "expected_target_names": sorted(path.name for path in expected),
            "observed_target_names": sorted(path.name for path in observed),
            "expected_normalized_identities": sorted(expected_map),
            "observed_normalized_identities": sorted(observed_map),
            "missing": missing,
            "extra": extra,
            "problems": problems,
            "enumeration_complete": not any(
                problem.startswith("vault_enumeration_failed:") for problem in problems
            ),
            "content_recorded": False,
        }
        return expected, evidence

    def _controlled_vault_targets(self, *, expected_receipt: bool) -> list[Path]:
        """Return only an exact phase set; never silently omit a target."""
        targets, discovery = self._exact_controlled_vault_targets(expected_receipt=expected_receipt)
        if not discovery.get("ok"):
            raise RuntimeError("vault_target_set_not_exact")
        return targets

    def _read_truth_unlocked(self, *, expected_receipt: bool) -> dict[str, Any]:
        """Read vault truth; temporary ACL lift is restored and verified in finally.

        Note: CAP_* strings are public role tokens, not OS capabilities. Host
        isolation for same-user denial relies on icacls deny ACE when applied.

        Every attempted target is inventoried *before* lift. The entire lift
        path is wrapped in an outer restoration try/finally so partial success
        followed by nonzero return, exception, or timeout still restores deny.
        """
        attempted_targets = self._controlled_vault_targets(expected_receipt=expected_receipt)
        try:
            return json.loads(self.truth_path.read_text(encoding="utf-8"))
        except PermissionError:
            # Resolve the exact token identity before any ACL mutation. The
            # captured account is reused for lift, every restore attempt, and
            # verification, so a later account-query failure cannot strand a
            # partially lifted target.
            user = self._current_user()
            identity_hold = self._hold_target_identities(attempted_targets)
            expected_identities = identity_hold["identities"]
            lift: dict[str, Any] = {
                "ok": False,
                "reason": "lift_not_attempted",
                "attempted_targets": [p.name for p in attempted_targets],
            }
            read_error: BaseException | None = None
            data: dict[str, Any] | None = None
            try:
                prelift_verify = self._verify_direct_denial(
                    targets=attempted_targets,
                    user=user,
                    expected_identities=expected_identities,
                )
                if not prelift_verify.get("denied"):
                    raise RuntimeError("vault_prelift_exact_denial_not_proven")
                try:
                    lift = self._icacls_remove_deny(targets=attempted_targets, user=user)
                    if not lift.get("ok"):
                        raise PermissionError(f"vault_acl_lift_failed:{lift.get('reason') or lift}")
                    try:
                        data = json.loads(self.truth_path.read_text(encoding="utf-8"))
                    except BaseException as exc:  # noqa: BLE001
                        read_error = exc
                        raise
                finally:
                    handle_restore = self._restore_handle_security_descriptors(
                        identity_hold["holds"]
                    )
                    restore = self._icacls_deny_current_user(targets=attempted_targets, user=user)
                    verify = self._verify_direct_denial(
                        targets=attempted_targets,
                        user=user,
                        expected_identities=expected_identities,
                    )
                    # Re-apply once if any exact original object is not both
                    # identity-bound and directly denied.
                    if not handle_restore.get("ok") or not verify.get("denied"):
                        handle_restore = self._restore_handle_security_descriptors(
                            identity_hold["holds"]
                        )
                        restore = self._icacls_deny_current_user(
                            targets=attempted_targets, user=user
                        )
                        verify = self._verify_direct_denial(
                            targets=attempted_targets,
                            user=user,
                            expected_identities=expected_identities,
                        )
                    if not handle_restore.get("ok") or not verify.get("denied"):
                        raise RuntimeError(
                            "vault_acl_restore_uncertain_or_failed:"
                            f"handle_restore={handle_restore.get('ok')},"
                            f"restore={restore.get('ok')},denied={verify.get('denied')},"
                            f"error={verify.get('error_class')},"
                            f"attempted={lift.get('attempted_targets')}"
                        ) from read_error
            finally:
                self._close_stable_identity_handles(identity_hold["holds"])
            if data is None:
                raise PermissionError("vault_acl_lift_read_returned_empty")
            return data

    def _current_user(self) -> str:
        """Return the exact qualified account name reported by the OS token."""
        import csv
        import subprocess

        proc = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError("current_user_token_query_failed")
        try:
            row = next(csv.reader([proc.stdout.strip()]))
        except (StopIteration, csv.Error) as exc:
            raise RuntimeError("current_user_token_query_unparseable") from exc
        if len(row) != 2 or not row[0].strip() or not row[1].strip().startswith("S-1-"):
            raise RuntimeError("current_user_token_identity_invalid")
        return row[0].strip()

    @staticmethod
    def _identity_key(path: Path) -> str:
        return str(path.resolve(strict=False)).casefold()

    @staticmethod
    def _get_handle_dacl_security_descriptor(handle: Any) -> bytes:
        import ctypes
        from ctypes import wintypes

        DACL_SECURITY_INFORMATION = 0x00000004
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        GetKernelObjectSecurity = advapi32.GetKernelObjectSecurity
        GetKernelObjectSecurity.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        GetKernelObjectSecurity.restype = wintypes.BOOL
        needed = wintypes.DWORD()
        GetKernelObjectSecurity(
            handle,
            DACL_SECURITY_INFORMATION,
            None,
            0,
            ctypes.byref(needed),
        )
        if needed.value == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(needed.value)
        if not GetKernelObjectSecurity(
            handle,
            DACL_SECURITY_INFORMATION,
            ctypes.cast(buffer, wintypes.LPVOID),
            needed.value,
            ctypes.byref(needed),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return bytes(buffer.raw[: needed.value])

    @staticmethod
    def _security_descriptor_dacl_sddl(security_descriptor: bytes) -> str:
        import ctypes
        from ctypes import wintypes

        DACL_SECURITY_INFORMATION = 0x00000004
        SDDL_REVISION_1 = 1
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ConvertSecurityDescriptorToStringSecurityDescriptorW = (
            advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
        )
        ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(wintypes.DWORD),
        ]
        ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
        LocalFree = kernel32.LocalFree
        LocalFree.argtypes = [wintypes.HLOCAL]
        LocalFree.restype = wintypes.HLOCAL

        descriptor_buffer = ctypes.create_string_buffer(
            security_descriptor, len(security_descriptor)
        )
        rendered = wintypes.LPWSTR()
        rendered_length = wintypes.DWORD()
        if not ConvertSecurityDescriptorToStringSecurityDescriptorW(
            ctypes.cast(descriptor_buffer, wintypes.LPVOID),
            SDDL_REVISION_1,
            DACL_SECURITY_INFORMATION,
            ctypes.byref(rendered),
            ctypes.byref(rendered_length),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return rendered.value or ""
        finally:
            if rendered:
                LocalFree(rendered)

    @staticmethod
    def _dacl_sddl_access_semantics(sddl: str) -> tuple[bool, str]:
        """Compare protection plus ordered ACEs; AI/AR are system-managed flags."""
        if not sddl.startswith("D:"):
            return False, sddl
        body = sddl[2:]
        ace_start = body.find("(")
        flags = body if ace_start < 0 else body[:ace_start]
        aces = "" if ace_start < 0 else body[ace_start:]
        return "P" in flags, aces

    @staticmethod
    def _open_stable_identity_handle(path: Path) -> dict[str, Any]:
        """Open one file without delete sharing and capture its 128-bit identity.

        The live handle allows other readers/writers needed by the bounded ACL
        operation, but blocks delete/rename/replacement until it is closed.
        """
        import ctypes
        from ctypes import wintypes

        FILE_READ_ATTRIBUTES = 0x0080
        READ_CONTROL = 0x00020000
        WRITE_DAC = 0x00040000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x00000080
        FILE_ID_INFO_CLASS = 18

        class FILE_ID_128(ctypes.Structure):
            _fields_ = [("Identifier", ctypes.c_ubyte * 16)]

        class FILE_ID_INFO(ctypes.Structure):
            _fields_ = [
                ("VolumeSerialNumber", ctypes.c_ulonglong),
                ("FileId", FILE_ID_128),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CreateFileW = kernel32.CreateFileW
        CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        CreateFileW.restype = wintypes.HANDLE
        GetFileInformationByHandleEx = kernel32.GetFileInformationByHandleEx
        GetFileInformationByHandleEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        GetFileInformationByHandleEx.restype = wintypes.BOOL
        CloseHandle = kernel32.CloseHandle
        CloseHandle.argtypes = [wintypes.HANDLE]
        CloseHandle.restype = wintypes.BOOL

        handle = CreateFileW(
            str(path),
            FILE_READ_ATTRIBUTES | READ_CONTROL | WRITE_DAC,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in (None, invalid_handle):
            error = ctypes.get_last_error()
            raise ctypes.WinError(error)
        info = FILE_ID_INFO()
        if not GetFileInformationByHandleEx(
            handle,
            FILE_ID_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            CloseHandle(handle)
            raise ctypes.WinError(error)
        try:
            security_descriptor = SealedTruthVault._get_handle_dacl_security_descriptor(handle)
            security_descriptor_sddl = SealedTruthVault._security_descriptor_dacl_sddl(
                security_descriptor
            )
        except BaseException:  # noqa: BLE001
            CloseHandle(handle)
            raise
        return {
            "handle": handle,
            "identity": (
                int(info.VolumeSerialNumber),
                bytes(info.FileId.Identifier),
            ),
            "prelift_dacl_security_descriptor": security_descriptor,
            "prelift_dacl_sddl": security_descriptor_sddl,
            "prelift_dacl_access_semantics": (
                SealedTruthVault._dacl_sddl_access_semantics(security_descriptor_sddl)
            ),
        }

    @staticmethod
    def _close_stable_identity_handles(holds: list[dict[str, Any]]) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CloseHandle = kernel32.CloseHandle
        CloseHandle.argtypes = [wintypes.HANDLE]
        CloseHandle.restype = wintypes.BOOL
        for hold in reversed(holds):
            handle = hold.get("handle")
            if handle not in (None, 0):
                CloseHandle(handle)

    def _hold_target_identities(self, targets: list[Path]) -> dict[str, Any]:
        """Bind every pre-lift path to a live, non-delete-shared file handle."""
        holds: list[dict[str, Any]] = []
        identities: dict[str, tuple[int, bytes]] = {}
        try:
            for path in targets:
                hold = self._open_stable_identity_handle(path)
                hold["path"] = path
                holds.append(hold)
                identities[self._identity_key(path)] = hold["identity"]
        except BaseException:  # noqa: BLE001
            self._close_stable_identity_handles(holds)
            raise
        return {"holds": holds, "identities": identities}

    def _capture_target_identity(self, path: Path) -> tuple[int, bytes]:
        hold = self._open_stable_identity_handle(path)
        try:
            return hold["identity"]
        finally:
            self._close_stable_identity_handles([hold])

    def _restore_handle_security_descriptors(self, holds: list[dict[str, Any]]) -> dict[str, Any]:
        """Restore each pre-lift DACL to the original object via its live handle."""
        import ctypes
        from ctypes import wintypes

        DACL_SECURITY_INFORMATION = 0x00000004
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        SetKernelObjectSecurity = advapi32.SetKernelObjectSecurity
        SetKernelObjectSecurity.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        SetKernelObjectSecurity.restype = wintypes.BOOL
        results: list[dict[str, Any]] = []
        for hold in holds:
            expected = bytes(hold["prelift_dacl_security_descriptor"])
            buffer = ctypes.create_string_buffer(expected, len(expected))
            applied = bool(
                SetKernelObjectSecurity(
                    hold["handle"],
                    DACL_SECURITY_INFORMATION,
                    ctypes.cast(buffer, wintypes.LPVOID),
                )
            )
            winerror = None if applied else ctypes.get_last_error()
            descriptor_matches = False
            if applied:
                try:
                    restored_descriptor = self._get_handle_dacl_security_descriptor(hold["handle"])
                    descriptor_matches = (
                        self._dacl_sddl_access_semantics(
                            self._security_descriptor_dacl_sddl(restored_descriptor)
                        )
                        == hold["prelift_dacl_access_semantics"]
                    )
                except BaseException:  # noqa: BLE001
                    descriptor_matches = False
            results.append(
                {
                    "path": Path(hold["path"]).name,
                    "applied": applied,
                    "descriptor_matches": descriptor_matches,
                    "winerror": winerror,
                    "content_recorded": False,
                }
            )
        return {
            "ok": bool(results)
            and all(item["applied"] and item["descriptor_matches"] for item in results),
            "results": results,
            "content_recorded": False,
        }

    def _verify_target_identities(
        self, targets: list[Path], expected_identities: dict[str, tuple[int, bytes]]
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for path in targets:
            expected = expected_identities.get(self._identity_key(path))
            matches = False
            error_class: str | None = None
            if expected is None:
                error_class = "IdentityBindingMissing"
            else:
                try:
                    matches = self._capture_target_identity(path) == expected
                except BaseException as exc:  # noqa: BLE001
                    error_class = type(exc).__name__
            results.append(
                {
                    "path": path.name,
                    "matches": matches,
                    "error_class": error_class,
                    "content_recorded": False,
                }
            )
        return {
            "ok": bool(results) and all(item["matches"] for item in results),
            "results": results,
            "content_recorded": False,
        }

    @staticmethod
    def _classify_open_failure(exc: BaseException) -> dict[str, Any]:
        """Classify open failures without recording content.

        Windows access-denied identity is winerror==5, or PermissionError with
        errno==13 (EACCES) when winerror is absent — the form this host Python
        surfaces after icacls DENY. Sharing violations, missing files, bare
        PermissionError injections without errno/winerror, and arbitrary OSError
        classes are distinct and never prove ACE restoration.
        """
        winerror = getattr(exc, "winerror", None)
        errno = getattr(exc, "errno", None)
        error_class = type(exc).__name__
        if winerror == WINERROR_ACCESS_DENIED:
            return {
                "error_kind": "access_denied",
                "error_class": error_class,
                "winerror": winerror,
                "errno": errno,
                "is_acl_access_denied": True,
            }
        if winerror == WINERROR_SHARING_VIOLATION:
            return {
                "error_kind": "sharing_violation",
                "error_class": error_class,
                "winerror": winerror,
                "errno": errno,
                "is_acl_access_denied": False,
            }
        if isinstance(exc, FileNotFoundError):
            return {
                "error_kind": "file_not_found",
                "error_class": error_class,
                "winerror": winerror,
                "errno": errno,
                "is_acl_access_denied": False,
            }
        # Real post-DENY open on this host: PermissionError(13, 'Permission denied')
        # with winerror left unset. Injected PermissionError("msg") has errno None.
        if isinstance(exc, PermissionError) and errno == 13:
            return {
                "error_kind": "access_denied",
                "error_class": error_class,
                "winerror": winerror,
                "errno": errno,
                "is_acl_access_denied": True,
            }
        if isinstance(exc, PermissionError):
            return {
                "error_kind": "permission_error_without_access_denied_identity",
                "error_class": error_class,
                "winerror": winerror,
                "errno": errno,
                "is_acl_access_denied": False,
            }
        if isinstance(exc, OSError):
            return {
                "error_kind": "os_error_other",
                "error_class": error_class,
                "winerror": winerror,
                "errno": errno,
                "is_acl_access_denied": False,
            }
        return {
            "error_kind": "injected_or_unrelated_exception",
            "error_class": error_class,
            "winerror": winerror,
            "errno": errno,
            "is_acl_access_denied": False,
        }

    @staticmethod
    def _parse_exact_icacls_rd(text: str, user: str, *, returncode: int) -> dict[str, Any]:
        """Accept exactly one current-account expression and only DENY(RD)."""
        occurrence_pattern = re.compile(
            rf"(?i)(?<!\S){re.escape(user)}:\(deny\)"
            rf"((?:\([^()\r\n]+\))+)(?=\s|$)"
        )
        rights = [match.group(1).casefold() for match in occurrence_pattern.finditer(text)]
        present = returncode == 0 and rights == ["(rd)"]
        return {
            "present": present,
            "occurrence_count": len(rights),
            "exact_read_deny_right": present,
        }

    @staticmethod
    def _exact_explicit_deny_rd_aces(aces: list[tuple[int, int]]) -> bool:
        """Exactly one explicit, unflagged FILE_READ_DATA deny ACE."""
        return aces == [(0x0001, 0x00)]

    def _deny_read_ace_present(self, path: Path, user: str) -> dict[str, Any]:
        """Independently verify exact current-user DENY read ACE.

        Uses Win32 GetNamedSecurityInfo so ACE presence can be proven even when
        post-DENY icacls listing fails with access denied for the current user.
        Falls back to icacls text when the Win32 path is unavailable. Never
        records file contents.
        """
        import subprocess

        user_l = user.casefold()
        try:
            win32 = self._deny_read_ace_present_win32(path, user)
        except Exception as exc:  # noqa: BLE001
            win32 = {
                "present": False,
                "ok": False,
                "query_ok": False,
                "method": "win32",
                "error_class": type(exc).__name__,
            }
        if win32.get("present") is True:
            return win32
        # Once enumeration began, any unreadable ACE or SID makes the whole DACL
        # proof incomplete. Text fallback must not erase that uncertainty.
        if win32.get("terminal_enumeration_failure") is True:
            return win32
        if (
            win32.get("method") == "win32"
            and win32.get("present") is False
            and (win32.get("query_ok") is True)
        ):
            return win32

        # icacls listing fallback (may fail with access denied post-DENY).
        try:
            proc = subprocess.run(
                ["icacls", str(path)],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "present": False,
                "ok": False,
                "error_class": type(exc).__name__,
                "returncode": None,
                "method": "icacls",
                "win32": win32,
            }
        chunks: list[str] = []
        for raw in (proc.stdout, proc.stderr):
            if raw is None:
                continue
            if isinstance(raw, bytes):
                for encoding in ("utf-8", "mbcs", "utf-16-le"):
                    try:
                        chunks.append(raw.decode(encoding))
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    chunks.append(raw.decode("utf-8", errors="replace"))
            else:
                chunks.append(str(raw))
        text = "\n".join(chunks)
        parsed = self._parse_exact_icacls_rd(text.casefold(), user_l, returncode=proc.returncode)
        present = parsed["present"] is True
        if present:
            return {
                "present": True,
                "ok": True,
                "returncode": proc.returncode,
                "method": "icacls",
                "exact_account_binding": True,
                "exact_read_deny_right": True,
                "occurrence_count": parsed["occurrence_count"],
                "content_recorded": False,
            }
        # Prefer a conclusive win32 absence over a failed icacls list.
        if win32.get("query_ok") is True:
            return win32
        return {
            "present": False,
            "ok": False,
            "returncode": proc.returncode,
            "method": "icacls",
            "win32": win32,
            "occurrence_count": parsed["occurrence_count"],
            "content_recorded": False,
        }

    def _deny_read_ace_present_win32(self, path: Path, user: str) -> dict[str, Any]:
        """Enumerate DACL via GetNamedSecurityInfo for current-user DENY read."""
        try:
            import ctypes
            from ctypes import wintypes
        except Exception as exc:  # noqa: BLE001
            return {
                "present": False,
                "ok": False,
                "query_ok": False,
                "method": "win32",
                "error_class": type(exc).__name__,
            }

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        SE_FILE_OBJECT = 1
        DACL_SECURITY_INFORMATION = 0x00000004
        ACCESS_DENIED_ACE_TYPE = 0x01
        # FILE_READ_DATA | FILE_READ_ATTRIBUTES | FILE_READ_EA | STANDARD_RIGHTS_READ | SYNCHRONIZE
        # icacls (R) maps to a read mask that includes FILE_READ_DATA (0x1).
        FILE_READ_DATA = 0x0001
        ERROR_SUCCESS = 0

        GetNamedSecurityInfoW = advapi32.GetNamedSecurityInfoW
        GetNamedSecurityInfoW.argtypes = [
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.LPVOID),
        ]
        GetNamedSecurityInfoW.restype = wintypes.DWORD

        GetAce = advapi32.GetAce
        LookupAccountSidW = advapi32.LookupAccountSidW
        LocalFree = kernel32.LocalFree

        owner = wintypes.LPVOID()
        group = wintypes.LPVOID()
        dacl = wintypes.LPVOID()
        sacl = wintypes.LPVOID()
        sd = wintypes.LPVOID()
        status = GetNamedSecurityInfoW(
            str(path),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            ctypes.byref(owner),
            ctypes.byref(group),
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(sd),
        )
        # A failed descriptor query is not structural proof of any exact ACE;
        # it can have unrelated causes. The caller may use a successful, exact
        # icacls descriptor listing as the independent fallback.
        if int(status) == WINERROR_ACCESS_DENIED:
            return {
                "present": False,
                "ok": False,
                "query_ok": False,
                "presence_basis": "security_descriptor_query_access_denied_not_proof",
                "method": "win32",
                "status": int(status),
                "content_recorded": False,
            }
        if status != ERROR_SUCCESS or not sd:
            return {
                "present": False,
                "ok": False,
                "query_ok": False,
                "method": "win32",
                "status": int(status),
                "content_recorded": False,
            }
        try:
            # ACCESS_ALLOWED_ACE / ACCESS_DENIED_ACE header layout
            class ACE_HEADER(ctypes.Structure):
                _fields_ = [
                    ("AceType", ctypes.c_ubyte),
                    ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", ctypes.c_ushort),
                ]

            class ACCESS_DENIED_ACE(ctypes.Structure):
                _fields_ = [
                    ("Header", ACE_HEADER),
                    ("Mask", wintypes.DWORD),
                    ("SidStart", wintypes.DWORD),
                ]

            # Walk ACEs
            p_dacl = ctypes.c_void_p(dacl.value)
            if not p_dacl:
                return {
                    "present": False,
                    "ok": False,
                    "query_ok": True,
                    "method": "win32",
                    "content_recorded": False,
                }

            # ACL structure: AclRevision, Sbz1, AclSize, AceCount, Sbz2
            class ACL(ctypes.Structure):
                _fields_ = [
                    ("AclRevision", ctypes.c_ubyte),
                    ("Sbz1", ctypes.c_ubyte),
                    ("AclSize", ctypes.c_ushort),
                    ("AceCount", ctypes.c_ushort),
                    ("Sbz2", ctypes.c_ushort),
                ]

            acl = ACL.from_address(p_dacl.value)
            user_l = user.casefold()
            current_user_deny_aces: list[tuple[int, int]] = []
            for index in range(int(acl.AceCount)):
                ace_ptr = ctypes.c_void_p()
                if not GetAce(p_dacl, index, ctypes.byref(ace_ptr)):
                    return {
                        "present": False,
                        "ok": False,
                        "query_ok": False,
                        "enumeration_complete": False,
                        "terminal_enumeration_failure": True,
                        "enumeration_failure": "get_ace_failed",
                        "ace_index": index,
                        "winerror": ctypes.get_last_error(),
                        "method": "win32",
                        "content_recorded": False,
                    }
                header = ACE_HEADER.from_address(ace_ptr.value)
                if header.AceType != ACCESS_DENIED_ACE_TYPE:
                    continue
                ace = ACCESS_DENIED_ACE.from_address(ace_ptr.value)
                # SID begins at SidStart offset inside the ACE.
                sid_addr = ace_ptr.value + ACCESS_DENIED_ACE.SidStart.offset
                name = ctypes.create_unicode_buffer(256)
                domain = ctypes.create_unicode_buffer(256)
                name_cch = wintypes.DWORD(256)
                domain_cch = wintypes.DWORD(256)
                use = wintypes.DWORD()
                if not LookupAccountSidW(
                    None,
                    ctypes.c_void_p(sid_addr),
                    name,
                    ctypes.byref(name_cch),
                    domain,
                    ctypes.byref(domain_cch),
                    ctypes.byref(use),
                ):
                    return {
                        "present": False,
                        "ok": False,
                        "query_ok": False,
                        "enumeration_complete": False,
                        "terminal_enumeration_failure": True,
                        "enumeration_failure": "lookup_account_sid_failed",
                        "ace_index": index,
                        "winerror": ctypes.get_last_error(),
                        "method": "win32",
                        "content_recorded": False,
                    }
                account = name.value.casefold()
                domain_name = domain.value.casefold()
                qualified = f"{domain_name}\\{account}" if domain_name else account
                if qualified == user_l:
                    current_user_deny_aces.append((int(ace.Mask), int(header.AceFlags)))
            present = self._exact_explicit_deny_rd_aces(current_user_deny_aces)
            return {
                "present": present,
                "ok": present,
                "query_ok": True,
                "enumeration_complete": True,
                "method": "win32",
                "exact_account_binding": True,
                "exact_read_deny_right": present,
                "current_user_deny_aces": current_user_deny_aces,
                "required_mask": FILE_READ_DATA,
                "required_ace_flags": 0,
                "content_recorded": False,
            }
        finally:
            if sd:
                LocalFree(sd)

    def _icacls_deny_current_user(
        self,
        targets: list[Path] | None = None,
        *,
        user: str | None = None,
        expected_receipt: bool | None = None,
    ) -> dict[str, Any]:
        """Explicit deny READ for current user — host subject process cannot open vault.

        A target already protected by exactly one verified current-user DENY(RD)
        ACE and a classified access-denied open is left unchanged. Otherwise,
        success requires icacls /deny returncode 0 plus those same two independent
        state checks. RD blocks content reads while leaving READ_CONTROL available
        for DACL verification. A failed command never succeeds from open failure alone.
        """
        import subprocess

        user = user or self._current_user()
        if targets is None:
            if expected_receipt is None:
                raise ValueError("expected_receipt_required_when_targets_omitted")
            target_list = self._controlled_vault_targets(expected_receipt=expected_receipt)
        else:
            target_list = list(targets)
        results: list[dict[str, Any]] = []
        for path in target_list:
            try:
                exists = path.exists()
            except OSError as exc:
                results.append(
                    {
                        "path": path.name,
                        "ok": False,
                        "returncode": None,
                        "error_class": type(exc).__name__,
                        "attempted": True,
                        "deny_ace_present": False,
                        "access_denied": False,
                    }
                )
                continue
            if not exists:
                results.append(
                    {
                        "path": path.name,
                        "ok": True,
                        "returncode": None,
                        "skipped": "missing",
                        "attempted": False,
                        "deny_ace_present": False,
                        "access_denied": False,
                    }
                )
                continue
            # Idempotent restoration: do not append a duplicate ACE when a
            # partially lifted batch left this target already protected by the
            # one exact DENY(RD) entry and a classified access-denied open.
            try:
                pre_ace = self._deny_read_ace_present(path, user)
            except Exception as exc:  # noqa: BLE001
                pre_ace = {
                    "present": False,
                    "ok": False,
                    "error_class": type(exc).__name__,
                }
            pre_open: dict[str, Any] = {
                "error_kind": "open_succeeded",
                "is_acl_access_denied": False,
                "error_class": None,
                "winerror": None,
            }
            try:
                with path.open("rb") as handle:
                    handle.read(1)
                pre_readable = True
            except BaseException as open_exc:  # noqa: BLE001
                pre_readable = False
                pre_open = self._classify_open_failure(open_exc)
            if (
                pre_ace.get("present") is True
                and not pre_readable
                and pre_open.get("is_acl_access_denied") is True
            ):
                results.append(
                    {
                        "path": path.name,
                        "returncode": None,
                        "ok": True,
                        "already_exact": True,
                        "deny_ace_present": True,
                        "access_denied": True,
                        "error_kind": pre_open.get("error_kind"),
                        "error_class": pre_open.get("error_class"),
                        "winerror": pre_open.get("winerror"),
                        "attempted": True,
                        "content_recorded": False,
                    }
                )
                continue
            try:
                proc = subprocess.run(
                    ["icacls", str(path), "/deny", f"{user}:(RD)"],
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                ace = self._deny_read_ace_present(path, user)
                open_cls: dict[str, Any] = {
                    "error_kind": "open_succeeded",
                    "is_acl_access_denied": False,
                    "error_class": None,
                    "winerror": None,
                }
                try:
                    with path.open("rb") as handle:
                        handle.read(1)
                    readable = True
                except BaseException as open_exc:  # noqa: BLE001
                    readable = False
                    open_cls = self._classify_open_failure(open_exc)
                access_denied = (not readable) and bool(open_cls.get("is_acl_access_denied"))
                # Require successful deny application + ACE presence + ACL denial.
                # Never accept nonzero/exceptional icacls as success via open alone.
                ok = proc.returncode == 0 and ace.get("present") is True and access_denied
                results.append(
                    {
                        "path": path.name,
                        "returncode": proc.returncode,
                        "ok": ok,
                        "deny_ace_present": ace.get("present") is True,
                        "access_denied": access_denied,
                        "error_kind": open_cls.get("error_kind"),
                        "error_class": open_cls.get("error_class"),
                        "winerror": open_cls.get("winerror"),
                        "attempted": True,
                        "content_recorded": False,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                # Subprocess exception is never success, even if a subsequent open
                # fails for an unrelated reason.
                open_cls = {
                    "error_kind": "not_probed_after_icacls_exception",
                    "is_acl_access_denied": False,
                    "error_class": None,
                    "winerror": None,
                }
                try:
                    with path.open("rb") as handle:
                        handle.read(1)
                except BaseException as open_exc:  # noqa: BLE001
                    open_cls = self._classify_open_failure(open_exc)
                results.append(
                    {
                        "path": path.name,
                        "returncode": None,
                        "ok": False,
                        "error_class": type(exc).__name__,
                        "deny_ace_present": False,
                        "access_denied": bool(open_cls.get("is_acl_access_denied")),
                        "open_error_kind": open_cls.get("error_kind"),
                        "open_winerror": open_cls.get("winerror"),
                        "attempted": True,
                        "content_recorded": False,
                    }
                )
        attempted = [r for r in results if r.get("attempted")]
        ok = bool(attempted) and all(r.get("ok") for r in attempted)
        if not attempted and not target_list:
            ok = False
        return {
            "ok": ok,
            "results": results,
            "attempted_targets": [r["path"] for r in attempted],
            "note": "icacls_deny_requires_return0_and_verified_deny_ace_and_access_denied",
        }

    def _icacls_remove_deny(
        self,
        targets: list[Path] | None = None,
        *,
        user: str | None = None,
        expected_receipt: bool | None = None,
    ) -> dict[str, Any]:
        """Remove deny ACE for each existing target; aggregate per-file failures.

        Does not raise mid-loop. Callers that temporarily lift ACLs must wrap the
        call in an outer restore try/finally.
        """
        import subprocess

        user = user or self._current_user()
        if targets is None:
            if expected_receipt is None:
                raise ValueError("expected_receipt_required_when_targets_omitted")
            target_list = self._controlled_vault_targets(expected_receipt=expected_receipt)
        else:
            target_list = list(targets)
        results: list[dict[str, Any]] = []
        for path in target_list:
            try:
                exists = path.exists()
            except OSError as exc:
                results.append(
                    {
                        "path": path.name,
                        "ok": False,
                        "returncode": None,
                        "error_class": type(exc).__name__,
                        "attempted": True,
                    }
                )
                continue
            if not exists:
                results.append(
                    {
                        "path": path.name,
                        "ok": True,
                        "returncode": None,
                        "skipped": "missing",
                        "attempted": False,
                    }
                )
                continue
            try:
                proc = subprocess.run(
                    ["icacls", str(path), "/remove:d", user],
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                results.append(
                    {
                        "path": path.name,
                        "returncode": proc.returncode,
                        "ok": proc.returncode == 0,
                        "attempted": True,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "path": path.name,
                        "returncode": None,
                        "ok": False,
                        "error_class": type(exc).__name__,
                        "attempted": True,
                    }
                )
        attempted = [r for r in results if r.get("attempted")]
        ok = all(r.get("ok") for r in attempted) if attempted else True
        reason = None
        if not ok:
            if any(r.get("error_class") == "TimeoutExpired" for r in attempted):
                reason = "partial_lift_timeout"
            elif any(r.get("error_class") for r in attempted):
                reason = "partial_lift_subprocess_exception"
            else:
                reason = "partial_lift_nonzero_return"
        return {
            "ok": ok,
            "results": results,
            "attempted_targets": [r["path"] for r in attempted],
            "reason": reason,
        }

    def _verify_direct_denial(
        self,
        targets: list[Path] | None = None,
        *,
        user: str | None = None,
        expected_identities: dict[str, tuple[int, bytes]] | None = None,
        expected_receipt: bool | None = None,
    ) -> dict[str, Any]:
        """Direct open must fail with Windows access-denied and verified DENY ACE.

        Sharing violations, FileNotFoundError, arbitrary OSError, and injected
        PermissionError without winerror==5 or errno==13 never prove restoration.
        Content is never recorded.
        """
        user = user or self._current_user()
        if targets is None:
            if expected_receipt is None:
                raise ValueError("expected_receipt_required_when_targets_omitted")
            target_list = self._controlled_vault_targets(expected_receipt=expected_receipt)
        else:
            target_list = list(targets)
        if not target_list:
            return {
                "denied": False,
                "readable": False,
                "error_class": "EmptyTargetSet",
                "error_kind": "empty_target_set",
                "content_recorded": False,
                "per_file": [],
            }
        per_file: list[dict[str, Any]] = []
        any_readable = False
        first_error: str | None = None
        first_kind: str | None = None
        for path in target_list:
            readable = False
            try:
                if not path.exists():
                    per_file.append(
                        {
                            "path": path.name,
                            "denied": False,
                            "readable": False,
                            "error_class": "FileNotFoundError",
                            "error_kind": "inventoried_target_missing",
                            "missing": True,
                            "deny_ace_present": False,
                            "content_recorded": False,
                        }
                    )
                    if first_error is None:
                        first_error = "FileNotFoundError"
                        first_kind = "inventoried_target_missing"
                    continue
            except OSError as exc:
                cls = self._classify_open_failure(exc)
                per_file.append(
                    {
                        "path": path.name,
                        "denied": False,
                        "readable": False,
                        "error_class": cls.get("error_class"),
                        "error_kind": cls.get("error_kind"),
                        "winerror": cls.get("winerror"),
                        "deny_ace_present": False,
                        "content_recorded": False,
                    }
                )
                if first_error is None:
                    first_error = cls.get("error_class")
                    first_kind = cls.get("error_kind")
                continue
            identity_matches: bool | None = None
            if expected_identities is not None:
                expected_identity = expected_identities.get(self._identity_key(path))
                if expected_identity is None:
                    per_file.append(
                        {
                            "path": path.name,
                            "denied": False,
                            "readable": False,
                            "error_class": "IdentityBindingMissing",
                            "error_kind": "prelift_identity_binding_missing",
                            "deny_ace_present": False,
                            "file_identity_matches": False,
                            "content_recorded": False,
                        }
                    )
                    if first_error is None:
                        first_error = "IdentityBindingMissing"
                        first_kind = "prelift_identity_binding_missing"
                    continue
                try:
                    identity_matches = self._capture_target_identity(path) == expected_identity
                except BaseException as exc:  # noqa: BLE001
                    per_file.append(
                        {
                            "path": path.name,
                            "denied": False,
                            "readable": False,
                            "error_class": type(exc).__name__,
                            "error_kind": "postrestore_identity_query_failed",
                            "deny_ace_present": False,
                            "file_identity_matches": False,
                            "content_recorded": False,
                        }
                    )
                    if first_error is None:
                        first_error = type(exc).__name__
                        first_kind = "postrestore_identity_query_failed"
                    continue
                if not identity_matches:
                    per_file.append(
                        {
                            "path": path.name,
                            "denied": False,
                            "readable": False,
                            "error_class": "FileIdentityMismatch",
                            "error_kind": "prelift_file_identity_replaced",
                            "deny_ace_present": False,
                            "file_identity_matches": False,
                            "content_recorded": False,
                        }
                    )
                    if first_error is None:
                        first_error = "FileIdentityMismatch"
                        first_kind = "prelift_file_identity_replaced"
                    continue
            try:
                ace = self._deny_read_ace_present(path, user)
            except Exception as exc:  # noqa: BLE001
                ace = {
                    "present": False,
                    "ok": False,
                    "error_class": type(exc).__name__,
                    "method": "verification_exception",
                }
            open_cls: dict[str, Any] = {
                "error_kind": "open_succeeded",
                "error_class": None,
                "winerror": None,
                "is_acl_access_denied": False,
            }
            try:
                with path.open("rb") as handle:
                    handle.read(1)
                readable = True
                any_readable = True
            except BaseException as exc:  # noqa: BLE001
                open_cls = self._classify_open_failure(exc)
                if first_error is None:
                    first_error = open_cls.get("error_class")
                    first_kind = open_cls.get("error_kind")
            acl_denied = (not readable) and bool(open_cls.get("is_acl_access_denied"))
            denied = acl_denied and ace.get("present") is True
            per_file.append(
                {
                    "path": path.name,
                    "denied": denied,
                    "readable": readable,
                    "error_class": open_cls.get("error_class"),
                    "error_kind": open_cls.get("error_kind"),
                    "winerror": open_cls.get("winerror"),
                    "deny_ace_present": ace.get("present") is True,
                    "file_identity_matches": identity_matches,
                    "content_recorded": False,
                }
            )
        denied = (
            bool(target_list)
            and len(per_file) == len(target_list)
            and all(p.get("denied") for p in per_file)
            and not any_readable
        )
        return {
            "denied": denied,
            "readable": any_readable,
            "error_class": first_error,
            "error_kind": first_kind,
            "content_recorded": False,
            "per_file": per_file,
        }

    def lock_down_host_reads(self, *, expected_receipt: bool) -> dict[str, Any]:
        """Apply host ACL only to one exact phase-specific target set."""
        targets, pre_target_set = self._exact_controlled_vault_targets(
            expected_receipt=expected_receipt
        )
        if not pre_target_set.get("ok"):
            return {
                "ok": False,
                "reason": "vault_target_set_not_exact_before_lockdown",
                "target_set_exact": False,
                "expected_receipt": expected_receipt,
                "pre_target_set": pre_target_set,
                "attempted_targets": [],
                "content_recorded": False,
                "authority": False,
            }
        user = self._current_user()
        try:
            identity_hold = self._hold_target_identities(targets)
        except BaseException as exc:  # noqa: BLE001
            return {
                "ok": False,
                "reason": "vault_lockdown_identity_binding_failed",
                "error_class": type(exc).__name__,
                "target_set_exact": False,
                "expected_receipt": expected_receipt,
                "expected_target_names": pre_target_set["expected_target_names"],
                "pre_target_set": pre_target_set,
                "attempted_targets": [],
                "content_recorded": False,
                "authority": False,
            }
        expected_identities = identity_hold["identities"]
        try:
            apply = self._icacls_deny_current_user(targets=targets, user=user)
            verify = self._verify_direct_denial(
                targets=targets,
                user=user,
                expected_identities=expected_identities,
            )
            _post_targets, post_target_set = self._exact_controlled_vault_targets(
                expected_receipt=expected_receipt
            )
            identity_verify = self._verify_target_identities(targets, expected_identities)
            target_set_exact = bool(pre_target_set.get("ok") and post_target_set.get("ok"))
            ok = bool(
                target_set_exact
                and apply.get("ok") is True
                and verify.get("denied") is True
                and identity_verify.get("ok") is True
            )
            return {
                "ok": ok,
                "target_set_exact": target_set_exact,
                "expected_receipt": expected_receipt,
                "expected_target_names": pre_target_set["expected_target_names"],
                "pre_target_set": pre_target_set,
                "post_target_set": post_target_set,
                "identity_binding": {
                    "ok": True,
                    "target_count": len(expected_identities),
                    "target_names": sorted(path.name for path in targets),
                    "non_delete_shared_handles_held_through_final_check": True,
                    "content_recorded": False,
                },
                "identity_verify": identity_verify,
                "vault_exists": self.truth_path.is_file(),
                "vault_readable_under_same_identity": verify.get("readable"),
                "read_error_type": verify.get("error_class"),
                "isolation_enforced": ok,
                "acl_apply": apply,
                "direct_verify": verify,
                "acl_restore_verified": verify.get("denied") is True,
                "attempted_targets": apply.get("attempted_targets") or [p.name for p in targets],
                "content_recorded": False,
                "capability_note": "CAP_* tokens are public role strings not OS capabilities",
                "authority": False,
            }
        finally:
            self._close_stable_identity_handles(identity_hold["holds"])

    def publish_lockdown_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """Atomically publish the lockdown receipt and seal its replacement inode.

        ``write_json`` publishes via ``os.replace``.  Replacing an already denied
        receipt therefore creates a new file identity without the old file's DENY
        ACE.  Resolve the account before publication, then normalize and verify
        every controlled target immediately after the replace.  The receipt is not
        rewritten after sealing.
        """
        pre_targets, pre_publication_target_set = self._exact_controlled_vault_targets(
            expected_receipt=False
        )
        if not pre_publication_target_set.get("ok"):
            return {
                "ok": False,
                "reason": "vault_pre_receipt_target_set_not_exact",
                "target_set_exact": False,
                "pre_publication_target_set": pre_publication_target_set,
                "attempted_targets": [],
                "content_recorded": False,
                "authority": False,
            }
        user = self._current_user()
        receipt_path = self.vault_root / "host_lockdown.v1.json"
        try:
            pre_identity_hold = self._hold_target_identities(pre_targets)
        except BaseException as exc:  # noqa: BLE001
            return {
                "ok": False,
                "reason": "vault_pre_receipt_identity_binding_failed",
                "error_class": type(exc).__name__,
                "target_set_exact": False,
                "expected_target_names": sorted(FINAL_TARGET_NAMES),
                "pre_publication_target_set": pre_publication_target_set,
                "attempted_targets": [],
                "content_recorded": False,
                "authority": False,
            }

        all_holds = list(pre_identity_hold["holds"])
        try:
            try:
                write_json(receipt_path, receipt)
            except BaseException as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "reason": "vault_lockdown_receipt_publication_failed",
                    "error_class": type(exc).__name__,
                    "target_set_exact": False,
                    "expected_target_names": sorted(FINAL_TARGET_NAMES),
                    "pre_publication_target_set": pre_publication_target_set,
                    "attempted_targets": [],
                    "content_recorded": False,
                    "authority": False,
                }

            targets, pre_seal_target_set = self._exact_controlled_vault_targets(
                expected_receipt=True
            )
            if not pre_seal_target_set.get("ok"):
                best_effort_apply = self._icacls_deny_current_user(targets=targets, user=user)
                return {
                    "ok": False,
                    "reason": "vault_final_target_set_not_exact_before_receipt_seal",
                    "target_set_exact": False,
                    "expected_target_names": sorted(FINAL_TARGET_NAMES),
                    "pre_publication_target_set": pre_publication_target_set,
                    "pre_seal_target_set": pre_seal_target_set,
                    "best_effort_acl_apply": best_effort_apply,
                    "attempted_targets": best_effort_apply.get("attempted_targets") or [],
                    "content_recorded": False,
                    "authority": False,
                }
            try:
                final_identity_hold = self._hold_target_identities(targets)
            except BaseException as exc:  # noqa: BLE001
                best_effort_apply = self._icacls_deny_current_user(targets=targets, user=user)
                return {
                    "ok": False,
                    "reason": "vault_final_identity_binding_failed",
                    "error_class": type(exc).__name__,
                    "target_set_exact": False,
                    "expected_target_names": sorted(FINAL_TARGET_NAMES),
                    "pre_publication_target_set": pre_publication_target_set,
                    "pre_seal_target_set": pre_seal_target_set,
                    "best_effort_acl_apply": best_effort_apply,
                    "attempted_targets": best_effort_apply.get("attempted_targets") or [],
                    "content_recorded": False,
                    "authority": False,
                }
            all_holds.extend(final_identity_hold["holds"])
            expected_identities = final_identity_hold["identities"]
            apply = self._icacls_deny_current_user(targets=targets, user=user)
            verify = self._verify_direct_denial(
                targets=targets,
                user=user,
                expected_identities=expected_identities,
            )
            _post_targets, post_seal_target_set = self._exact_controlled_vault_targets(
                expected_receipt=True
            )
            identity_verify = self._verify_target_identities(targets, expected_identities)
            target_set_exact = bool(
                pre_publication_target_set.get("ok")
                and pre_seal_target_set.get("ok")
                and post_seal_target_set.get("ok")
                and len(pre_targets) == len(PRE_RECEIPT_TARGET_NAMES)
                and len(targets) == len(FINAL_TARGET_NAMES)
            )
            ok = bool(
                target_set_exact
                and apply.get("ok") is True
                and verify.get("denied") is True
                and identity_verify.get("ok") is True
            )
            return {
                "ok": ok,
                "target_set_exact": target_set_exact,
                "expected_target_names": sorted(FINAL_TARGET_NAMES),
                "pre_publication_target_set": pre_publication_target_set,
                "pre_seal_target_set": pre_seal_target_set,
                "post_seal_target_set": post_seal_target_set,
                "identity_binding": {
                    "ok": True,
                    "target_count": len(expected_identities),
                    "target_names": sorted(path.name for path in targets),
                    "non_delete_shared_handles_held_through_final_check": True,
                    "pre_receipt_targets_held_across_publication": True,
                    "content_recorded": False,
                },
                "identity_verify": identity_verify,
                "receipt_path": receipt_path.name,
                "receipt_resealed": ok,
                "acl_apply": apply,
                "final_verify": verify,
                "attempted_targets": apply.get("attempted_targets")
                or [path.name for path in targets],
                "content_recorded": False,
                "authority": False,
            }
        finally:
            self._close_stable_identity_handles(all_holds)

    @contextmanager
    def hold_verified_locked_phase(self, *, expected_receipt: bool) -> Iterator[dict[str, Any]]:
        """Verify a sealed phase while preventing target replacement until exit."""
        targets, pre_target_set = self._exact_controlled_vault_targets(
            expected_receipt=expected_receipt
        )
        if not pre_target_set.get("ok"):
            yield {
                "ok": False,
                "reason": "vault_target_set_not_exact_before_live_verification",
                "target_set_exact": False,
                "expected_receipt": expected_receipt,
                "expected_target_names": pre_target_set["expected_target_names"],
                "pre_target_set": pre_target_set,
                "attempted_targets": [],
                "content_recorded": False,
                "authority": False,
            }
            return

        try:
            identity_hold = self._hold_target_identities(targets)
        except BaseException as exc:  # noqa: BLE001
            yield {
                "ok": False,
                "reason": "vault_live_identity_binding_failed",
                "error_class": type(exc).__name__,
                "target_set_exact": False,
                "expected_receipt": expected_receipt,
                "expected_target_names": pre_target_set["expected_target_names"],
                "pre_target_set": pre_target_set,
                "attempted_targets": [],
                "content_recorded": False,
                "authority": False,
            }
            return

        expected_identities = identity_hold["identities"]
        try:
            user = self._current_user()
            direct_verify = self._verify_direct_denial(
                targets=targets,
                user=user,
                expected_identities=expected_identities,
            )
            _post_targets, post_target_set = self._exact_controlled_vault_targets(
                expected_receipt=expected_receipt
            )
            identity_verify = self._verify_target_identities(targets, expected_identities)
            target_set_exact = bool(pre_target_set.get("ok") and post_target_set.get("ok"))
            ok = bool(
                target_set_exact
                and direct_verify.get("denied") is True
                and identity_verify.get("ok") is True
            )
            yield {
                "ok": ok,
                "target_set_exact": target_set_exact,
                "expected_receipt": expected_receipt,
                "expected_target_names": pre_target_set["expected_target_names"],
                "pre_target_set": pre_target_set,
                "post_target_set": post_target_set,
                "identity_binding": {
                    "ok": True,
                    "target_count": len(expected_identities),
                    "target_names": sorted(path.name for path in targets),
                    "non_delete_shared_handles_held_until_gate_exit": True,
                    "content_recorded": False,
                },
                "identity_verify": identity_verify,
                "direct_verify": direct_verify,
                "attempted_targets": [path.name for path in targets],
                "content_recorded": False,
                "authority": False,
            }
        finally:
            self._close_stable_identity_handles(identity_hold["holds"])

    def verify_locked_phase(self, *, expected_receipt: bool) -> dict[str, Any]:
        """One-shot live verification; use the guard when work follows immediately."""
        with self.hold_verified_locked_phase(expected_receipt=expected_receipt) as verification:
            return verification

    def unlock_host_reads(self, *, expected_receipt: bool) -> dict[str, Any]:
        """Permanent unlock boundary with outer restore on partial/failed lift.

        On full success deny ACEs remain removed (caller owns the unlocked state).
        On partial success, exception, or timeout, restore is attempted for every
        inventoried target before the failure is reported.
        """
        attempted_targets = self._controlled_vault_targets(expected_receipt=expected_receipt)
        user = self._current_user()
        identity_hold = self._hold_target_identities(attempted_targets)
        expected_identities = identity_hold["identities"]
        lift: dict[str, Any]
        try:
            try:
                prelift_verify = self._verify_direct_denial(
                    targets=attempted_targets,
                    user=user,
                    expected_identities=expected_identities,
                )
                if not prelift_verify.get("denied"):
                    raise RuntimeError("vault_prelift_exact_denial_not_proven")
                lift = self._icacls_remove_deny(targets=attempted_targets, user=user)
                if not lift.get("ok"):
                    raise RuntimeError(f"vault_acl_unlock_failed:{lift.get('reason') or lift}")
                identity_verify = self._verify_target_identities(
                    attempted_targets, expected_identities
                )
                if not identity_verify.get("ok"):
                    raise RuntimeError("vault_acl_unlock_target_identity_changed")
                return {
                    "ok": True,
                    "results": lift.get("results"),
                    "attempted_targets": lift.get("attempted_targets"),
                    "restored_after_failure": False,
                    "prelift_file_identity_bound": True,
                }
            except Exception as exc:  # noqa: BLE001
                handle_restore = self._restore_handle_security_descriptors(identity_hold["holds"])
                restore = self._icacls_deny_current_user(targets=attempted_targets, user=user)
                verify = self._verify_direct_denial(
                    targets=attempted_targets,
                    user=user,
                    expected_identities=expected_identities,
                )
                return {
                    "ok": False,
                    "reason": "vault_acl_unlock_partial_or_failed_restored",
                    "error_class": type(exc).__name__,
                    "lift": lift if "lift" in locals() else None,
                    "handle_restore": handle_restore,
                    "restore": restore,
                    "restore_denied": bool(handle_restore.get("ok") and verify.get("denied")),
                    "attempted_targets": [p.name for p in attempted_targets],
                    "restored_after_failure": True,
                    "prelift_file_identity_bound": True,
                    "content_recorded": False,
                }
        finally:
            self._close_stable_identity_handles(identity_hold["holds"])
