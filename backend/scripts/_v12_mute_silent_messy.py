# -*- coding: utf-8 -*-
"""Mute audio on silent V12 shots that still fail unexpected_speech QA; then rescore."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db import Project, SessionLocal, Shot, ensure_schema, init_db  # noqa: E402
from app.domain.video_speech import extract_expected_speech, speech_expected  # noqa: E402
from app.video_qa import force_silent_audio  # noqa: E402
from app.video_scores import clear_shot_video_score, score_shot_video  # noqa: E402

PID = "6d9be75e-0799-4626-a646-c5036c13311a"
LOG = Path(__file__).resolve().parent / "_v12_mute_silent_messy.log"
AUDIO_ISSUES = {
    "unexpected_speech",
    "possible_foreign_speech",
}


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


async def main() -> int:
    init_db()
    ensure_schema()
    db = SessionLocal()
    try:
        project = db.get(Project, PID)
        if not project:
            log("missing project")
            return 1
        targets: list[Shot] = []
        for s in db.query(Shot).filter(Shot.project_id == PID).order_by(Shot.order_index):
            if not (s.video_path or "").strip():
                continue
            lines = json.loads(s.lines_json or "[]")
            expected = extract_expected_speech(
                s.h3_prompt or "",
                lines=lines if isinstance(lines, list) else [],
                narration=s.narration or "",
            )
            if speech_expected(expected):
                continue
            qa = json.loads(s.video_qa_json or "{}")
            issues = set(qa.get("issues") or [])
            tr = (qa.get("transcript") or "").strip()
            if not (issues & AUDIO_ISSUES) and not (len(tr) >= 4):
                continue
            targets.append(s)
        log(f"targets={len(targets)}")
        ok = 0
        for s in targets:
            abs_path = Path(settings.data_dir) / s.video_path
            try:
                force_silent_audio(abs_path)
                clear_shot_video_score(s)
                db.add(s)
                db.commit()
                db.refresh(s)
                out = await score_shot_video(db, project, s, allow_regen=False)
                ok += 1
                log(f"muted shot#{s.order_index} {s.id[:8]} score={out.get('score')} {out.get('comment')}")
            except Exception as exc:  # noqa: BLE001
                log(f"FAIL shot#{s.order_index} {s.id[:8]}: {exc}")
        left = 0
        for s in db.query(Shot).filter(Shot.project_id == PID):
            qa = json.loads(s.video_qa_json or "{}")
            issues = set(qa.get("issues") or [])
            tr = (qa.get("transcript") or "").strip()
            if issues & AUDIO_ISSUES or (not qa.get("speech_expected") and len(tr) >= 4):
                left += 1
        log(f"DONE muted={ok} remaining_messy={left}")
        return 0 if left == 0 else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
