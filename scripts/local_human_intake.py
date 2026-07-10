"""Token-efficient, content-local intake for documents and audio/video.

Documents are converted with MarkItDown's local-file-only API. Audio and video
are transcribed with faster-whisper; media bytes are never sent to a hosted
speech service. A missing model may be downloaded unless --local-files-only is
used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

AUDIO_VIDEO_SUFFIXES = frozenset(
    {
        ".aac",
        ".flac",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".opus",
        ".wav",
        ".webm",
    }
)
DEFAULT_MODEL_ROOT = Path(
    os.environ.get(
        "XINAO_HUMAN_MODEL_ROOT",
        r"D:\XINAO_RESEARCH_RUNTIME\state\human-capabilities\models",
    )
)


def _source_file(raw_path: str | Path) -> Path:
    raw = str(raw_path)
    if "://" in raw:
        raise ValueError("Only local files are accepted; URLs are not allowed")
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"Expected a file: {path}")
    return path


def _is_media(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_VIDEO_SUFFIXES


def _clock(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _document_text(path: Path) -> str:
    from markitdown import MarkItDown

    converter = MarkItDown(enable_plugins=False)
    result = converter.convert_local(path)
    text = getattr(result, "text_content", None) or getattr(result, "markdown", None)
    if not isinstance(text, str):
        raise RuntimeError("MarkItDown returned no textual content")
    return text.strip()


def _requested_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import ctranslate2

        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"


def _load_whisper_model(
    model_name: str,
    *,
    device: str,
    compute_type: str | None,
    download_root: Path,
    local_files_only: bool,
) -> tuple[Any, str, str]:
    from faster_whisper import WhisperModel

    requested_auto = device == "auto"
    resolved_device = _requested_device(device)
    resolved_compute = compute_type or ("float16" if resolved_device == "cuda" else "int8")
    download_root.mkdir(parents=True, exist_ok=True)

    try:
        model = WhisperModel(
            model_name,
            device=resolved_device,
            compute_type=resolved_compute,
            download_root=str(download_root),
            local_files_only=local_files_only,
        )
    except (RuntimeError, ValueError):
        if not requested_auto or resolved_device == "cpu":
            raise
        resolved_device = "cpu"
        resolved_compute = compute_type or "int8"
        model = WhisperModel(
            model_name,
            device=resolved_device,
            compute_type=resolved_compute,
            download_root=str(download_root),
            local_files_only=local_files_only,
        )
    return model, resolved_device, resolved_compute


def _transcribe_media(
    path: Path,
    *,
    model_name: str,
    language: str | None,
    device: str,
    compute_type: str | None,
    download_root: Path,
    local_files_only: bool,
    vad_filter: bool,
) -> dict[str, Any]:
    model, actual_device, actual_compute = _load_whisper_model(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
        local_files_only=local_files_only,
    )
    segment_stream, info = model.transcribe(
        str(path),
        language=language,
        beam_size=5,
        vad_filter=vad_filter,
    )
    segments = [
        {
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "text": str(segment.text).strip(),
        }
        for segment in segment_stream
        if str(segment.text).strip()
    ]
    detected_language = str(getattr(info, "language", language or "unknown"))
    probability = getattr(info, "language_probability", None)
    duration = getattr(info, "duration", None)
    lines = [
        "# Local transcript",
        "",
        f"- Engine: faster-whisper {model_name}",
        f"- Language: {detected_language}",
        f"- Device: {actual_device} ({actual_compute})",
        "",
    ]
    lines.extend(
        f"[{_clock(segment['start'])} --> {_clock(segment['end'])}] {segment['text']}"
        for segment in segments
    )
    return {
        "schema_version": "xinao.human-intake.v1",
        "operation": "local_media_transcription",
        "local_only": True,
        "content_network_egress": False,
        "model_download_may_use_network": not local_files_only,
        "source": str(path),
        "engine": "faster-whisper",
        "model": model_name,
        "device": actual_device,
        "compute_type": actual_compute,
        "language": detected_language,
        "language_probability": round(float(probability), 6) if probability is not None else None,
        "duration_seconds": round(float(duration), 3) if duration is not None else None,
        "segments": segments,
        "content": "\n".join(lines).rstrip(),
    }


def intake(
    source: str | Path,
    *,
    model_name: str = "small",
    language: str | None = None,
    device: str = "auto",
    compute_type: str | None = None,
    download_root: Path = DEFAULT_MODEL_ROOT,
    local_files_only: bool = False,
    vad_filter: bool = True,
) -> dict[str, Any]:
    path = _source_file(source)
    if _is_media(path):
        return _transcribe_media(
            path,
            model_name=model_name,
            language=language,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
            local_files_only=local_files_only,
            vad_filter=vad_filter,
        )

    content = _document_text(path)
    return {
        "schema_version": "xinao.human-intake.v1",
        "operation": "local_document_conversion",
        "local_only": True,
        "content_network_egress": False,
        "model_download_may_use_network": False,
        "source": str(path),
        "engine": "markitdown.convert_local",
        "content": content,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Local document, audio, or video file")
    parser.add_argument("-o", "--output", type=Path, help="Write output to this file")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--model", default="small", help="faster-whisper model name or path")
    parser.add_argument("--language", help="BCP-47-ish language code such as zh or en")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--compute-type", help="CTranslate2 compute type override")
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="Refuse model downloads; media content is always local regardless",
    )
    parser.add_argument("--no-vad", action="store_true", help="Disable voice-activity filtering")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = intake(
            args.source,
            model_name=args.model,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            download_root=args.model_root,
            local_files_only=args.local_files_only,
            vad_filter=not args.no_vad,
        )
    except Exception as exc:
        print(f"local-human-intake: {exc}", file=sys.stderr)
        return 2

    rendered = (
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.format == "json"
        else str(result["content"])
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered.rstrip() + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
