from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import local_human_intake as intake_module


def test_clock_formats_milliseconds() -> None:
    assert intake_module._clock(3_661.234) == "01:01:01.234"


def test_source_rejects_urls_and_directories(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="URLs are not allowed"):
        intake_module._source_file("https://example.com/report.pdf")
    with pytest.raises(ValueError, match="Expected a file"):
        intake_module._source_file(tmp_path)


def test_document_intake_uses_local_conversion(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("LOCAL_DOCUMENT_OK", encoding="utf-8")

    result = intake_module.intake(source)

    assert result["operation"] == "local_document_conversion"
    assert result["local_only"] is True
    assert result["content_network_egress"] is False
    assert "LOCAL_DOCUMENT_OK" in result["content"]


def test_media_intake_routes_to_faster_whisper_not_markitdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "meeting.WAV"
    source.write_bytes(b"RIFF-placeholder")
    expected = {"operation": "local_media_transcription", "content": "ok"}
    calls: list[Path] = []

    def fake_transcribe(path: Path, **_: object) -> dict[str, object]:
        calls.append(path)
        return expected

    monkeypatch.setattr(intake_module, "_transcribe_media", fake_transcribe)
    monkeypatch.setattr(
        intake_module,
        "_document_text",
        lambda _: pytest.fail("media must never use MarkItDown audio transcription"),
    )

    assert intake_module.intake(source) is expected
    assert calls == [source.resolve()]


def test_transcript_contains_timestamps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "voice.wav"
    source.write_bytes(b"RIFF-placeholder")

    class FakeModel:
        def transcribe(self, *_: object, **__: object):
            segments = [SimpleNamespace(start=1.25, end=2.5, text=" hello ")]
            info = SimpleNamespace(language="en", language_probability=0.99, duration=2.5)
            return iter(segments), info

    monkeypatch.setattr(
        intake_module,
        "_load_whisper_model",
        lambda *args, **kwargs: (FakeModel(), "cpu", "int8"),
    )

    result = intake_module.intake(source, model_name="tiny", device="cpu")

    assert result["segments"] == [{"start": 1.25, "end": 2.5, "text": "hello"}]
    assert "[00:00:01.250 --> 00:00:02.500] hello" in result["content"]
    assert result["content_network_egress"] is False
