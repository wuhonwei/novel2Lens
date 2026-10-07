"""ffmpeg keyframe / wav extraction and optional local ASR for video QA."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

_DEFAULT_FRACS = (0.10, 0.35, 0.60, 0.85)
_whisper_model = None
_asr_disabled_reason: str | None = None


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def probe_duration_s(video: Path) -> float:
    cmd = [
        _ffprobe(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.decode(errors='replace')[:300]}")
    return max(0.1, float((proc.stdout or b"0").decode().strip() or "0"))


def extract_keyframes(video: Path, work: Path, count: int | None = None) -> list[Path]:
    """Extract evenly spaced keyframes into work dir; return PNG paths."""
    if not video.is_file():
        raise FileNotFoundError(str(video))
    n = int(count if count is not None else settings.video_qa_frame_count)
    n = max(1, min(8, n))
    work.mkdir(parents=True, exist_ok=True)
    duration = probe_duration_s(video)
    fracs = _DEFAULT_FRACS[:n] if n <= len(_DEFAULT_FRACS) else [
        (i + 0.5) / n for i in range(n)
    ]
    out: list[Path] = []
    for i, frac in enumerate(fracs):
        t = max(0.0, min(duration - 0.05, duration * float(frac)))
        dest = work / f"frame_{i:02d}.png"
        cmd = [
            _ffmpeg(),
            "-y",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, check=False)
        if proc.returncode != 0 or not dest.is_file():
            raise RuntimeError(
                f"ffmpeg keyframe failed t={t}: {proc.stderr.decode(errors='replace')[:300]}"
            )
        out.append(dest)
    return out


def force_silent_audio(video: Path) -> Path:
    """Replace the video's audio with silence (H3 often invents babble on silent shots)."""
    if not video.is_file():
        raise FileNotFoundError(str(video))
    tmp = video.with_suffix(".silent.tmp.mp4")
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        str(video),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg mute failed: {proc.stderr.decode(errors='replace')[:300]}")
    tmp.replace(video)
    return video


def extract_wav(video: Path, wav: Path) -> Path:
    if not video.is_file():
        raise FileNotFoundError(str(video))
    wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0 or not wav.is_file():
        raise RuntimeError(f"ffmpeg wav failed: {proc.stderr.decode(errors='replace')[:300]}")
    return wav


def asr_available() -> bool:
    if _asr_disabled_reason:
        return False
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def _get_whisper_model():
    """Load Whisper once; on failure disable ASR for the process (avoid Hub retry storms)."""
    global _whisper_model, _asr_disabled_reason
    if _asr_disabled_reason:
        return None
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(
            settings.video_qa_asr_model,
            device=settings.video_qa_asr_device,
            compute_type="int8" if settings.video_qa_asr_device == "cpu" else "default",
        )
        return _whisper_model
    except Exception as exc:
        _asr_disabled_reason = f"{type(exc).__name__}: {exc}"
        log.warning("ASR disabled for this process: %s", _asr_disabled_reason)
        return None


def load_wav_mono_f32(wav: Path, sample_rate: int = 16000):
    """Decode wav to mono float32 via ffmpeg (avoids PyAV API mismatches)."""
    import numpy as np

    if not wav.is_file():
        raise FileNotFoundError(str(wav))
    cmd = [
        _ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(wav),
        "-ac",
        "1",
        "-ar",
        str(int(sample_rate)),
        "-f",
        "f32le",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"ffmpeg pcm failed: {proc.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def transcribe_wav(wav: Path) -> str:
    """Return ASR text, or empty string if ASR unavailable / fails."""
    if not wav.is_file():
        return ""
    if not asr_available():
        return ""
    model = _get_whisper_model()
    if model is None:
        return ""
    global _asr_disabled_reason
    try:
        # Feed numpy audio so faster-whisper does not call av.open (broken on some PyAV builds).
        audio = load_wav_mono_f32(wav, sample_rate=16000)
        if audio.size == 0:
            return ""
        segments, _info = model.transcribe(audio, language="zh", vad_filter=True)
        parts = [seg.text.strip() for seg in segments if (seg.text or "").strip()]
        return "".join(parts).strip()
    except TypeError as exc:
        # e.g. unexpected API mismatch — do not retry every shot
        _asr_disabled_reason = f"TypeError: {exc}"
        log.warning("ASR disabled after transcribe incompatibility: %s", _asr_disabled_reason)
        return ""
    except Exception:
        log.exception("ASR transcribe failed for %s", wav)
        return ""
