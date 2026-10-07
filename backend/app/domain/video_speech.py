"""Parse expected H3 speech and score ASR transcripts for video QA."""
from __future__ import annotations

import re
from typing import Any

_SAID_RE = re.compile(r"说道：\s*[「『“\"]([^」』”\"]+)[」』”\"]")
_VO_RE = re.compile(r"画外口播：\s*[「『“\"]([^」』”\"]+)[」』”\"]")
_NAR_RE = re.compile(r"旁白（画外音）：\s*([^\n]+?)(?=\s*(?:画面中可辨认|本镜无人声|人声语言锁定|$)|。)")
_QUOTE_RE = re.compile(r"[「『“\"]([^」』”\"]{2,160})[」』”\"]")


def _norm(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+", "", t)
    for ch in "，。！？、；：…·「」『』“”\"'":
        t = t.replace(ch, "")
    return t.lower()


def extract_expected_speech(
    h3_prompt: str,
    *,
    lines: list[dict[str, Any]] | None = None,
    narration: str = "",
) -> list[str]:
    """Collect spoken lines the video should contain."""
    out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        q = (s or "").strip()
        if len(q) < 2:
            return
        if q in ("无", "无。"):
            return
        key = _norm(q)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(q)

    for ln in lines or []:
        add(str(ln.get("dialogue") or ""))

    nar = (narration or "").strip()
    if nar and nar not in ("无", "无。"):
        if nar.startswith("画外口播："):
            for m in _QUOTE_RE.finditer(nar):
                add(m.group(1))
        else:
            add(nar)

    text = h3_prompt or ""
    for m in _SAID_RE.finditer(text):
        add(m.group(1))
    for m in _VO_RE.finditer(text):
        add(m.group(1))
    m = _NAR_RE.search(text)
    if m:
        add(m.group(1))
    return out


def speech_expected(expected: list[str] | None) -> bool:
    return bool(expected)


def score_transcript(expected: list[str], transcript: str) -> dict[str, Any]:
    """Score ASR transcript against expected speech (0–100)."""
    issues: list[str] = []
    tr = (transcript or "").strip()
    tr_n = _norm(tr)
    exp = [e for e in (expected or []) if (e or "").strip()]

    if not exp:
        if not tr_n or len(tr_n) < 4:
            return {"score": 100, "issues": []}
        # Any substantial speech on a silent shot is bad; foreign scripts worse.
        if re.search(r"[\u3040-\u30ff\u3400-\u4dbf]", tr) and not re.search(r"[\u4e00-\u9fff]", tr):
            issues.append("unexpected_speech")
            issues.append("possible_foreign_speech")
            return {"score": 20, "issues": issues}
        issues.append("unexpected_speech")
        return {"score": 35, "issues": issues}

    if not tr_n:
        issues.append("missing_speech")
        return {"score": 15, "issues": issues}

    hits = 0
    for e in exp:
        en = _norm(e)
        if not en:
            continue
        if en in tr_n or tr_n in en:
            hits += 1
            continue
        # Token overlap: share >= half of characters
        shared = sum(1 for c in en if c in tr_n)
        if shared >= max(2, len(en) // 2):
            hits += 1
    ratio = hits / max(1, len(exp))
    score = int(round(ratio * 100))
    if ratio < 0.5:
        issues.append("dialogue_mismatch")
    if re.search(r"[\u3040-\u30ff]", tr) and hits == 0:
        issues.append("possible_foreign_speech")
        score = min(score, 25)
    return {"score": max(0, min(100, score)), "issues": issues}


def combine_video_scores(
    visual: int | None,
    audio: int | None,
    *,
    speech_expected: bool,
) -> dict[str, Any]:
    """Combine visual/audio scores with weights from the design spec."""
    hints: list[str] = []
    if visual is None and audio is None:
        return {
            "score": 0,
            "weights": {"visual": 1.0, "audio": 0.0},
            "comment_hint": "no_scores",
        }
    if audio is None:
        w = {"visual": 1.0, "audio": 0.0}
        hints.append("audio_skipped")
        score = int(visual or 0)
    elif speech_expected:
        w = {"visual": 0.6, "audio": 0.4}
        score = int(round(0.6 * float(visual or 0) + 0.4 * float(audio)))
    else:
        w = {"visual": 0.75, "audio": 0.25}
        score = int(round(0.75 * float(visual or 0) + 0.25 * float(audio)))
    return {
        "score": max(0, min(100, score)),
        "weights": w,
        "comment_hint": ",".join(hints),
    }
