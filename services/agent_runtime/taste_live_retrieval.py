"""Explicit, bounded live retrieval for mechanically qualified Taste evidence.

Cold source/evaluation/shadow evidence never becomes prompt context by merely
existing.  A caller must explicitly activate a native score chain which the
native verifier recomputes as qualified.  Activation then emits a small,
content-addressed source-side card; held-out evaluation oracles, scorers, raw
rollouts, and full shadow bundles stay cold and are never copied into the live
retrieval root.

The production hook then performs a conservative lexical lookup over sealed
cards and renders at most one non-authoritative contrast.  Missing, malformed,
irrelevant, or unqualified evidence therefore contributes no prompt text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Mapping
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from services.agent_runtime.execution_contract import canonical_json_bytes

LIVE_ACTIVATION_SCHEMA = "s.taste_live_activation.v1"
QUALIFICATION_RECEIPT_SCHEMA = "xinao.taste_qualification_receipt.v1"
DEFAULT_TASTE_ACTIVATION_ROOT = Path(
    os.environ.get(
        "S_TASTE_ACTIVATION_ROOT",
        r"D:\XINAO_RESEARCH_RUNTIME\state\S_Taste_Corpus\activated",
    )
)
S_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_EVENT_ID_RE = re.compile(r"^evt_[0-9a-f]{64}$")
_ASCII_WORD_RE = re.compile(r"[a-z0-9_]{4,}", re.IGNORECASE)
_HAN_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_CARDS = 16
_MIN_ASCII_CONCEPTS = 3
_MIN_HAN_MATCHED_CHARACTERS = 6
_MIN_HAN_DISTINCT_BLOCKS = 2
_MAX_RELEVANCE_CHARS = 4_000
_MAX_RENDER_CHARS = 2_400
_QUALIFICATION_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "authority",
        "completion_claim_allowed",
        "qualified",
        "candidate_sha256",
        "baseline_outcome_sha256",
        "treatment_outcome_sha256",
        "bindings",
        "comparisons",
        "cold_controls",
        "receipt_sha256",
    }
)
_QUALIFICATION_COLD_CONTROLS = {
    "fresh_distinct_runs": True,
    "cache_used": False,
    "hooks_enabled": False,
    "oracle_exposed": False,
    "live_retrieval_used": False,
    "hot_mutation_used": False,
    "trajectories_sealed": True,
}
_COMMON_ASCII_LEXEMES = {
    "answer",
    "assistant",
    "codex",
    "continue",
    "current",
    "please",
    "request",
    "user",
}


class TasteLiveRetrievalError(ValueError):
    """A live activation or sealed retrieval card failed closed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(code: str, message: str) -> None:
    raise TasteLiveRetrievalError(code, message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _seal(value: Mapping[str, object], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = _sha(canonical_json_bytes(result))
    return result


def _verify_seal(value: Mapping[str, object], field: str) -> str:
    observed = value.get(field)
    if not isinstance(observed, str) or _SHA_RE.fullmatch(observed) is None:
        _fail("HASH_INVALID", f"{field} is not a SHA-256 identity")
    unsigned = dict(value)
    unsigned.pop(field, None)
    if _sha(canonical_json_bytes(unsigned)) != observed:
        _fail("HASH_MISMATCH", f"{field} does not seal the record")
    return observed


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or path.is_junction()
    except (AttributeError, OSError):
        return path.is_symlink()


def _path_traverses_link(path: Path) -> bool:
    candidate = Path(path)
    for existing in (candidate, *candidate.parents):
        try:
            if existing.exists() and _is_link(existing):
                return True
        except OSError:
            return True
    return False


def _read_regular(path: Path, field: str) -> bytes:
    path = Path(path)
    if _path_traverses_link(path) or not path.is_file():
        _fail("FILE_INVALID", f"{field} is not a regular non-link file")
    lexical = path.lstat()
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or not (1 <= before.st_size <= _MAX_FILE_BYTES):
                _fail("FILE_INVALID", f"{field} has an invalid size or type")
            raw = handle.read(_MAX_FILE_BYTES + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise TasteLiveRetrievalError("FILE_INVALID", f"{field} could not be read") from exc
    final_lexical = path.lstat()
    if (
        len(raw) != before.st_size
        or len(raw) > _MAX_FILE_BYTES
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or (before.st_dev, before.st_ino) != (lexical.st_dev, lexical.st_ino)
        or (after.st_dev, after.st_ino) != (final_lexical.st_dev, final_lexical.st_ino)
        or _is_link(path)
    ):
        _fail("FILE_CHANGED", f"{field} changed during readback")
    return raw


def _json(raw: bytes, field: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TasteLiveRetrievalError(
            "JSON_INVALID", f"{field} is not canonical UTF-8 JSON"
        ) from exc
    if not isinstance(value, Mapping):
        _fail("JSON_INVALID", f"{field} must be an object")
    return dict(value)


def _binding(relative_path: str, raw: bytes) -> dict[str, object]:
    return {
        "relative_path": relative_path,
        "sha256": _sha(raw),
        "size_bytes": len(raw),
    }


def _bound_file(root: Path, value: object, field: str) -> bytes:
    if not isinstance(value, Mapping) or set(value) != {
        "relative_path",
        "sha256",
        "size_bytes",
    }:
        _fail("FILE_BINDING_INVALID", f"{field} binding is invalid")
    relative = value.get("relative_path")
    expected_sha = value.get("sha256")
    expected_size = value.get("size_bytes")
    if (
        not isinstance(relative, str)
        or Path(relative).name != relative
        or not isinstance(expected_sha, str)
        or _SHA_RE.fullmatch(expected_sha) is None
        or not isinstance(expected_size, int)
        or expected_size < 1
    ):
        _fail("FILE_BINDING_INVALID", f"{field} identity is invalid")
    raw = _read_regular(root / relative, field)
    if len(raw) != expected_size or _sha(raw) != expected_sha:
        _fail("FILE_BINDING_MISMATCH", f"{field} bytes drifted")
    return raw


def _verify_qualification_receipt(
    raw: bytes, *, candidate_sha256: str, receipt_sha256: str
) -> dict[str, object]:
    receipt = _json(raw, "qualification receipt")
    if (
        set(receipt) != _QUALIFICATION_RECEIPT_KEYS
        or receipt.get("schema_version") != QUALIFICATION_RECEIPT_SCHEMA
        or _verify_seal(receipt, "receipt_sha256") != receipt_sha256
        or receipt.get("authority") is not False
        or receipt.get("completion_claim_allowed") is not False
        or receipt.get("qualified") is not True
        or receipt.get("candidate_sha256") != candidate_sha256
        or any(
            not isinstance(receipt.get(field), str)
            or _SHA_RE.fullmatch(str(receipt.get(field))) is None
            for field in (
                "candidate_sha256",
                "baseline_outcome_sha256",
                "treatment_outcome_sha256",
            )
        )
        or not isinstance(receipt.get("bindings"), Mapping)
        or not isinstance(receipt.get("comparisons"), Mapping)
        or receipt.get("cold_controls") != _QUALIFICATION_COLD_CONTROLS
    ):
        _fail("QUALIFICATION_INVALID", "qualification receipt policy or identity drifted")
    return receipt


def _message(value: object, *, role: str, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"event_id", "role", "content"}:
        _fail("PROJECTION_INVALID", f"{field} is not an exact source message")
    event_id = value.get("event_id")
    content = value.get("content")
    if (
        not isinstance(event_id, str)
        or _EVENT_ID_RE.fullmatch(event_id) is None
        or value.get("role") != role
        or not isinstance(content, str)
        or not content.strip()
    ):
        _fail("PROJECTION_INVALID", f"{field} identity, role, or text is invalid")
    return {"event_id": event_id, "role": role, "content": content}


def _validate_projection(raw: bytes) -> dict[str, object]:
    projection = _json(raw, "source projection")
    if (
        set(projection) != {"schema_version", "mode", "episodes"}
        or projection.get("schema_version") != "s.taste_source_projection.v1"
        or projection.get("mode") != "source_contrastive_episode"
    ):
        _fail("PROJECTION_INVALID", "unsupported source projection policy")
    episodes = projection.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != 1:
        _fail("PROJECTION_INVALID", "a live card must contain exactly one source episode")
    episode = episodes[0]
    if not isinstance(episode, Mapping) or set(episode) != {
        "prefix",
        "bad_continuation",
        "human_corrections",
        "desired_continuation",
    }:
        _fail("PROJECTION_INVALID", "source episode has an invalid shape")
    prefix = episode.get("prefix")
    corrections = episode.get("human_corrections")
    if (
        not isinstance(prefix, list)
        or not prefix
        or not isinstance(corrections, list)
        or not corrections
    ):
        _fail("PROJECTION_INVALID", "source episode lacks a prefix or human correction")
    normalized_prefix: list[dict[str, str]] = []
    for index, row in enumerate(prefix):
        if not isinstance(row, Mapping) or row.get("role") not in {"user", "assistant"}:
            _fail("PROJECTION_INVALID", f"prefix[{index}] has an invalid speaker")
        normalized_prefix.append(_message(row, role=str(row["role"]), field=f"prefix[{index}]"))
    if normalized_prefix[-1]["role"] != "user":
        _fail("PROJECTION_INVALID", "source prefix must end at the current user surface")
    normalized = {
        "prefix": normalized_prefix,
        "bad_continuation": _message(
            episode.get("bad_continuation"), role="assistant", field="bad_continuation"
        ),
        "human_corrections": [
            _message(row, role="user", field=f"human_corrections[{index}]")
            for index, row in enumerate(corrections)
        ],
        "desired_continuation": _message(
            episode.get("desired_continuation"),
            role="assistant",
            field="desired_continuation",
        ),
    }
    if normalized != episode:
        _fail("PROJECTION_INVALID", "source projection is not canonically normalized")
    return projection


def activate_native_qualified_taste(
    *,
    score_dir: Path,
    pair_dir: Path,
    plan_dir: Path,
    source_dir: Path,
    evaluation_dir: Path,
    activation_root: Path = DEFAULT_TASTE_ACTIVATION_ROOT,
) -> dict[str, object]:
    """Explicitly activate one recomputed, qualified native Taste chain."""

    from services.agent_runtime.taste_codex_shadow import (
        verify_codex_shadow_pair,
        verify_codex_shadow_score,
    )
    from services.agent_runtime.taste_corpus import verify_qualification_plan

    score = verify_codex_shadow_score(
        score_dir,
        pair_dir=pair_dir,
        plan_dir=plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    qualification = score.get("qualification_receipt")
    if score.get("qualified") is not True or not isinstance(qualification, Mapping):
        _fail("NOT_QUALIFIED", "the native contrast did not pass its held-out qualification")

    plan = verify_qualification_plan(
        plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    pair = verify_codex_shadow_pair(
        pair_dir,
        plan_dir=plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    source = plan.get("source")
    evaluation = plan.get("evaluation")
    candidate = plan.get("candidate")
    if not all(isinstance(item, Mapping) for item in (source, evaluation, candidate)):
        _fail("CHAIN_INVALID", "the verified native chain is incomplete")
    assert isinstance(source, Mapping)
    assert isinstance(evaluation, Mapping)
    assert isinstance(candidate, Mapping)
    projection_raw = source.get("treatment_condition")
    if not isinstance(projection_raw, bytes):
        _fail("CHAIN_INVALID", "the verified source lacks its mechanical projection")
    _validate_projection(projection_raw)
    receipt_sha = qualification.get("receipt_sha256")
    candidate_sha = candidate.get("candidate_sha256")
    if (
        not isinstance(receipt_sha, str)
        or _SHA_RE.fullmatch(receipt_sha) is None
        or not isinstance(candidate_sha, str)
        or _SHA_RE.fullmatch(candidate_sha) is None
        or qualification.get("qualified") is not True
        or qualification.get("candidate_sha256") != candidate_sha
    ):
        _fail("CHAIN_INVALID", "the qualification receipt identity is invalid")

    chain = {
        "source_bundle_sha256": source["source_bundle_sha256"],
        "evaluation_bundle_sha256": evaluation["evaluation_bundle_sha256"],
        "plan_bundle_sha256": plan["plan_bundle_sha256"],
        "pair_bundle_sha256": pair["pair_bundle_sha256"],
        "score_bundle_sha256": score["score_bundle_sha256"],
        "candidate_sha256": candidate_sha,
        "qualification_receipt_sha256": receipt_sha,
    }
    if any(
        not isinstance(value, str) or _SHA_RE.fullmatch(value) is None for value in chain.values()
    ):
        _fail("CHAIN_INVALID", "the native chain contains an invalid content identity")
    qualification_raw = canonical_json_bytes(dict(qualification))
    _verify_qualification_receipt(
        qualification_raw,
        candidate_sha256=str(candidate_sha),
        receipt_sha256=str(receipt_sha),
    )
    files = {
        "source_projection": _binding("source_projection.json", projection_raw),
        "qualification_receipt": _binding("qualification_receipt.json", qualification_raw),
    }
    manifest = _seal(
        {
            "schema_version": LIVE_ACTIVATION_SCHEMA,
            "authority": False,
            "completion_claim_allowed": False,
            "live_retrievable": True,
            "selection_policy": {
                "mode": "current_prompt_lexical_relevance",
                "maximum_cards": 1,
                "current_prompt_included": False,
            },
            "activation_source": {
                "mode": "full_native_chain_verified_once_at_activation",
                "hot_path_full_chain_replay": False,
                "trust_boundary": "trusted_S_activation_writer_not_hostile_same_user",
            },
            "chain": chain,
            "files": files,
        },
        "activation_sha256",
    )
    activation_sha = str(manifest["activation_sha256"])
    manifest_raw = canonical_json_bytes(manifest)

    root = Path(activation_root)
    if _path_traverses_link(root) or (root.exists() and not root.is_dir()):
        _fail("ACTIVATION_ROOT_INVALID", "Taste activation root is not a plain directory")
    root.mkdir(parents=True, exist_ok=True)
    if _path_traverses_link(root) or not root.is_dir():
        _fail("ACTIVATION_ROOT_INVALID", "Taste activation root changed during creation")
    target = root / activation_sha
    if target.exists():
        verified = verify_live_activation_card(target)
        if verified["manifest"] != manifest:
            _fail("ACTIVATION_CONFLICT", "content-addressed activation identity conflicted")
        return {
            "status": "REUSED",
            "activation_directory": str(target.resolve()),
            "activation_sha256": activation_sha,
            "candidate_sha256": candidate_sha,
        }

    staging = root / f".staging-{activation_sha}-{uuid.uuid4().hex}"
    staging.mkdir(exist_ok=False)
    try:
        for relative, raw in {
            "source_projection.json": projection_raw,
            "qualification_receipt.json": qualification_raw,
        }.items():
            with (staging / relative).open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        with (staging / "manifest.json").open("xb") as handle:
            handle.write(manifest_raw)
            handle.flush()
            os.fsync(handle.fileno())
        _verify_activation_directory(staging, expected_name=None)
        try:
            staging.rename(target)
        except OSError:
            if not target.exists():
                raise
            verified = verify_live_activation_card(target)
            if verified["manifest"] != manifest:
                _fail("ACTIVATION_CONFLICT", "concurrent activation identity conflicted")
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    verified = verify_live_activation_card(target)
    return {
        "status": "ACTIVATED",
        "activation_directory": str(target.resolve()),
        "activation_sha256": verified["activation_sha256"],
        "candidate_sha256": candidate_sha,
    }


def _verify_activation_directory(card_dir: Path, *, expected_name: str | None) -> dict[str, object]:
    root = Path(card_dir)
    if _path_traverses_link(root) or not root.is_dir():
        _fail("CARD_INVALID", "Taste activation card is not a plain directory")
    manifest_raw = _read_regular(root / "manifest.json", "activation manifest")
    manifest = _json(manifest_raw, "activation manifest")
    activation_sha = _verify_seal(manifest, "activation_sha256")
    if (
        set(manifest)
        != {
            "schema_version",
            "authority",
            "completion_claim_allowed",
            "live_retrievable",
            "selection_policy",
            "chain",
            "activation_source",
            "files",
            "activation_sha256",
        }
        or manifest.get("schema_version") != LIVE_ACTIVATION_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("completion_claim_allowed") is not False
        or manifest.get("live_retrievable") is not True
        or manifest.get("selection_policy")
        != {
            "mode": "current_prompt_lexical_relevance",
            "maximum_cards": 1,
            "current_prompt_included": False,
        }
        or manifest.get("activation_source")
        != {
            "mode": "full_native_chain_verified_once_at_activation",
            "hot_path_full_chain_replay": False,
            "trust_boundary": "trusted_S_activation_writer_not_hostile_same_user",
        }
        or (expected_name is not None and root.name != activation_sha)
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("CARD_INVALID", "Taste activation policy or identity drifted")
    chain = manifest.get("chain")
    expected_chain_keys = {
        "source_bundle_sha256",
        "evaluation_bundle_sha256",
        "plan_bundle_sha256",
        "pair_bundle_sha256",
        "score_bundle_sha256",
        "candidate_sha256",
        "qualification_receipt_sha256",
    }
    if (
        not isinstance(chain, Mapping)
        or set(chain) != expected_chain_keys
        or any(
            not isinstance(value, str) or _SHA_RE.fullmatch(value) is None
            for value in chain.values()
        )
    ):
        _fail("CHAIN_INVALID", "Taste activation chain is incomplete")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != {
        "source_projection",
        "qualification_receipt",
    }:
        _fail("FILE_BINDING_INVALID", "Taste activation file bindings are incomplete")
    projection_raw = _bound_file(root, files["source_projection"], "source projection")
    qualification_raw = _bound_file(root, files["qualification_receipt"], "qualification receipt")
    projection = _validate_projection(projection_raw)
    _verify_qualification_receipt(
        qualification_raw,
        candidate_sha256=str(chain["candidate_sha256"]),
        receipt_sha256=str(chain["qualification_receipt_sha256"]),
    )
    if {path.name for path in root.iterdir()} != {
        "manifest.json",
        "source_projection.json",
        "qualification_receipt.json",
    }:
        _fail("FILE_SET_MISMATCH", "activation root contains undeclared objects")
    return {
        "manifest": manifest,
        "activation_sha256": activation_sha,
        "candidate_sha256": chain["candidate_sha256"],
        "projection": projection,
    }


def verify_live_activation_card(card_dir: Path) -> dict[str, object]:
    """Verify the small card emitted after one full native qualification replay."""

    return _verify_activation_directory(Path(card_dir), expected_name=Path(card_dir).name)


def _inside_s_body(*, cwd: Path | None = None) -> bool:
    try:
        actual = (Path.cwd() if cwd is None else Path(cwd)).resolve()
        root = S_WORKSPACE_ROOT.resolve()
    except OSError:
        return False
    return actual == root or root in actual.parents


def _ascii_concepts(text: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _ASCII_WORD_RE.finditer(text)
        if match.group(0).casefold() not in _COMMON_ASCII_LEXEMES
    }


def _han_characters(text: str) -> str:
    return "".join(_HAN_CHAR_RE.findall(text[:_MAX_RELEVANCE_CHARS]))


def _relevance_strength(query: str, source_surface: str) -> int:
    query = query[:_MAX_RELEVANCE_CHARS]
    source_surface = source_surface[:_MAX_RELEVANCE_CHARS]
    ascii_overlap = len(_ascii_concepts(query) & _ascii_concepts(source_surface))
    if ascii_overlap >= _MIN_ASCII_CONCEPTS:
        return ascii_overlap

    query_han = _han_characters(query)
    source_han = _han_characters(source_surface)
    if not query_han or not source_han:
        return 0
    blocks = [
        block.size
        for block in SequenceMatcher(
            None,
            query_han,
            source_han,
            autojunk=False,
        ).get_matching_blocks()
        if block.size >= 2
    ]
    if (len(blocks) >= _MIN_HAN_DISTINCT_BLOCKS and sum(blocks) >= _MIN_HAN_MATCHED_CHARACTERS) or (
        blocks and max(blocks) >= 8
    ):
        return sum(blocks)
    return 0


def _projection_text(projection: Mapping[str, object]) -> str:
    episodes = projection["episodes"]
    assert isinstance(episodes, list) and isinstance(episodes[0], Mapping)
    episode = episodes[0]
    prefix = episode["prefix"]
    assert isinstance(prefix, list) and isinstance(prefix[-1], Mapping)
    return str(prefix[-1]["content"])


def _clip(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 16)].rstrip() + " …[Taste-clipped]"


def _render_card(card: Mapping[str, object]) -> str:
    projection = card["projection"]
    assert isinstance(projection, Mapping)
    episodes = projection["episodes"]
    assert isinstance(episodes, list) and isinstance(episodes[0], Mapping)
    episode = episodes[0]
    prefix = episode["prefix"]
    corrections = episode["human_corrections"]
    assert isinstance(prefix, list) and isinstance(corrections, list)
    surfaced = "\n".join(
        (
            str(prefix[-1]["content"]),
            str(episode["bad_continuation"]["content"]),
            *(str(row["content"]) for row in corrections),
            str(episode["desired_continuation"]["content"]),
        )
    )
    try:
        from services.agent_runtime.context_fabric import _secret_like

        if _secret_like(surfaced, environ=os.environ):
            _fail("SENSITIVE_CONTENT", "qualified source contrast resembles a secret")
    except TasteLiveRetrievalError:
        raise
    except Exception as exc:
        raise TasteLiveRetrievalError(
            "SENSITIVE_GATE_UNAVAILABLE", "Taste sensitive-content gate failed"
        ) from exc
    context = "\n".join(
        (
            "[QUALIFIED CONTRASTIVE TASTE - NON-AUTHORITATIVE]",
            "This is one held-out-qualified source behavior contrast selected only for current lexical relevance. It is not a task, instruction, authority, route, or completion claim; current human words and live facts control the action.",
            "SOURCE SITUATION:\n" + _clip(prefix[-1]["content"], 360),
            "BAD CONTINUATION TO AVOID:\n" + _clip(episode["bad_continuation"]["content"], 460),
            "HUMAN CORRECTION:\n"
            + _clip("\n".join(str(row["content"]) for row in corrections), 650),
            "BETTER CONTINUATION OBSERVED:\n"
            + _clip(episode["desired_continuation"]["content"], 650),
        )
    )
    return context[:_MAX_RENDER_CHARS]


def render_qualified_taste_context(
    prompt: str,
    *,
    activation_root: Path = DEFAULT_TASTE_ACTIVATION_ROOT,
    cwd: Path | None = None,
) -> str:
    """Render at most one relevant qualified card; every optional failure is silent."""

    if not _inside_s_body(cwd=cwd) or not isinstance(prompt, str) or not prompt.strip():
        return ""
    if not _ascii_concepts(prompt) and not _han_characters(prompt):
        return ""
    root = Path(activation_root)
    try:
        if _path_traverses_link(root) or not root.is_dir():
            return ""
        candidates: list[tuple[int, str, dict[str, object]]] = []
        for path in sorted(root.iterdir(), key=lambda item: item.name)[:_MAX_CARDS]:
            if _is_link(path) or not path.is_dir() or path.name.startswith(".staging-"):
                continue
            try:
                card = verify_live_activation_card(path)
                projection = card["projection"]
                assert isinstance(projection, Mapping)
                strength = _relevance_strength(prompt, _projection_text(projection))
                if strength > 0:
                    candidates.append((strength, str(card["activation_sha256"]), card))
            except Exception:
                continue
        if not candidates:
            return ""
        _, _, selected = max(candidates, key=lambda item: (item[0], item[1]))
        return _render_card(selected)
    except Exception:
        return ""


__all__ = [
    "DEFAULT_TASTE_ACTIVATION_ROOT",
    "LIVE_ACTIVATION_SCHEMA",
    "QUALIFICATION_RECEIPT_SCHEMA",
    "TasteLiveRetrievalError",
    "activate_native_qualified_taste",
    "render_qualified_taste_context",
    "verify_live_activation_card",
]
