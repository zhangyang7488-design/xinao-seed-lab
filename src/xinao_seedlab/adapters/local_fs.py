from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from xinao_seedlab.domain.models import Episode, EvidenceRecord


def utf8_safe(value: object) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, list):
        return [utf8_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(utf8_safe(k)): utf8_safe(v) for k, v in value.items()}
    return value


def to_plain(value: object) -> Any:
    if isinstance(value, BaseModel):
        return utf8_safe(value.model_dump(mode="json"))
    if isinstance(value, str):
        return utf8_safe(value)
    if isinstance(value, list):
        return [to_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(utf8_safe(k)): to_plain(v) for k, v in value.items()}
    return value


class LocalFsEvidenceStore:
    def __init__(self, runtime_root: str | Path = "D:/XINAO_RESEARCH_RUNTIME") -> None:
        self.runtime_root = Path(runtime_root)

    def episode_dir(self, episode_id: str) -> Path:
        path = self.runtime_root / "runs" / "episodes" / episode_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def reset_episode(self, episode_id: str) -> str:
        path = self.runtime_root / "runs" / "episodes" / episode_id
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _write_json(self, path: Path, value: object) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(to_plain(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(path)

    def _append_jsonl(self, path: Path, value: object) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(to_plain(value), ensure_ascii=False) + "\n")
        return str(path)

    def write_episode(self, episode: Episode) -> str:
        return self._write_json(self.episode_dir(episode.episode_id) / "episode.json", episode)

    def append_trace(self, episode_id: str, event: object) -> str:
        return self._append_jsonl(self.episode_dir(episode_id) / "episode_trace.jsonl", event)

    def append_evidence(self, record: EvidenceRecord) -> str:
        return self._append_jsonl(self.episode_dir(record.episode_id) / "evidence_ledger.jsonl", record)

    def write_artifact(self, episode_id: str, name: str, value: object) -> str:
        return self._write_json(self.episode_dir(episode_id) / name, value)

    def append_lineage_event(self, value: object) -> str:
        return self._append_jsonl(self.runtime_root / "lineage" / "openlineage" / "events.ndjson", value)

    def write_readback(self, episode_id: str, markdown: str) -> str:
        path = self.runtime_root / "readback" / "zh" / f"{episode_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        return str(path)
