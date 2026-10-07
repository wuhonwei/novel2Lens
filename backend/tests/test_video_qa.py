# -*- coding: utf-8 -*-
from pathlib import Path

from app.video_qa import asr_available, extract_keyframes, extract_wav, probe_duration_s, transcribe_wav


def test_extract_keyframes_calls_ffmpeg(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    work = tmp_path / "work"
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        # Create the output path from -update / last arg before that
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x89PNG\r\n\x1a\n")
        class R:
            returncode = 0
            stdout = b""
            stderr = b""
        return R()

    monkeypatch.setattr("app.video_qa.subprocess.run", fake_run)
    monkeypatch.setattr("app.video_qa.probe_duration_s", lambda _p: 10.0)
    frames = extract_keyframes(video, work, count=4)
    assert len(frames) == 4
    assert all(p.is_file() for p in frames)
    assert any("ffmpeg" in c[0] or c[0].endswith("ffmpeg") or c[0].endswith("ffmpeg.exe") for c in calls)


def test_force_silent_audio_rewrites_via_ffmpeg(tmp_path, monkeypatch):
    from app import video_qa

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake-mp4")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        out = Path(cmd[-1])
        out.write_bytes(b"muted-mp4")
        class R:
            returncode = 0
            stdout = b""
            stderr = b""
        return R()

    monkeypatch.setattr(video_qa, "subprocess", type("S", (), {"run": staticmethod(fake_run)}))
    out = video_qa.force_silent_audio(video)
    assert out == video
    assert video.read_bytes() == b"muted-mp4"
    assert any("anullsrc" in " ".join(c) for c in calls)


def test_extract_wav(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    wav = tmp_path / "a.wav"

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"RIFF")
        class R:
            returncode = 0
            stdout = b""
            stderr = b""
        return R()

    monkeypatch.setattr("app.video_qa.subprocess.run", fake_run)
    out = extract_wav(video, wav)
    assert out == wav
    assert wav.is_file()


def test_transcribe_returns_empty_when_asr_unavailable(tmp_path, monkeypatch):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr("app.video_qa.asr_available", lambda: False)
    text = transcribe_wav(wav)
    assert text == ""


def test_transcribe_uses_ffmpeg_pcm_not_path(tmp_path, monkeypatch):
    import numpy as np

    from app import video_qa

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr(video_qa, "_asr_disabled_reason", None)
    monkeypatch.setattr(video_qa, "asr_available", lambda: True)
    monkeypatch.setattr(video_qa, "load_wav_mono_f32", lambda _p, sample_rate=16000: np.zeros(1600, dtype=np.float32))

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            assert hasattr(audio, "dtype")
            return [type("S", (), {"text": "你好"})()], None

    monkeypatch.setattr(video_qa, "_get_whisper_model", lambda: FakeModel())
    assert video_qa.transcribe_wav(wav) == "你好"


def test_probe_duration_parses_ffprobe(monkeypatch):
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = b"12.5\n"
            stderr = b""
        return R()

    monkeypatch.setattr("app.video_qa.subprocess.run", fake_run)
    assert probe_duration_s(Path("x.mp4")) == 12.5
