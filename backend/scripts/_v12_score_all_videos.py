# -*- coding: utf-8 -*-
"""Score all V12 shot videos (vision keyframes + local ASR). Resumable."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.video_qa as video_qa  # noqa: E402
from app.db import Project, SessionLocal, Shot, ensure_schema, init_db  # noqa: E402
from app.video_qa import asr_available  # noqa: E402
from app.video_scores import clear_shot_video_score, score_shot_video, summarize_video_scores  # noqa: E402

PID = "6d9be75e-0799-4626-a646-c5036c13311a"
LOG = Path(__file__).resolve().parent / "_v12_score_videos.log"
REPORT = Path(__file__).resolve().parent / "_v12_score_videos_report.json"
FORCE_SKIP_ASR = "--skip-asr" in sys.argv
RESET_SCORES = "--reset" in sys.argv


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


async def main() -> int:
    init_db()
    ensure_schema()
    if FORCE_SKIP_ASR:
        video_qa._asr_disabled_reason = "forced: PyAV/faster-whisper incompat"
    log(f"asr_available={asr_available()} reason={video_qa._asr_disabled_reason}")
    db = SessionLocal()
    try:
        project = db.get(Project, PID)
        if not project:
            log("project missing")
            return 1
        shots = (
            db.query(Shot)
            .filter(Shot.project_id == PID)
            .order_by(Shot.order_index)
            .all()
        )
        if RESET_SCORES:
            n = 0
            for s in shots:
                if s.video_score is not None or (s.video_qa_json or "{}") not in ("", "{}"):
                    clear_shot_video_score(s)
                    db.add(s)
                    n += 1
            db.commit()
            log(f"reset_scores={n}")
            shots = (
                db.query(Shot)
                .filter(Shot.project_id == PID)
                .order_by(Shot.order_index)
                .all()
            )
        targets = [
            s
            for s in shots
            if (s.video_path or "").strip() and (s.h3_prompt or "").strip()
        ]
        pending = [s for s in targets if s.video_score is None]
        log(f"total_with_video={len(targets)} pending={len(pending)} already={len(targets)-len(pending)}")
        errors: list[str] = []
        scored = 0
        t0 = time.time()
        for i, shot in enumerate(pending, 1):
            try:
                out = await score_shot_video(db, project, shot, allow_regen=False)
                scored += 1
                log(
                    f"[{i}/{len(pending)}] shot#{shot.order_index} "
                    f"score={out.get('score')} comment={(out.get('comment') or '')[:80]}"
                )
            except Exception as exc:  # noqa: BLE001
                err = f"shot#{shot.order_index} {shot.id}: {type(exc).__name__}: {exc}"
                errors.append(err)
                log(f"[{i}/{len(pending)}] FAIL {err}")
            if i % 5 == 0 or i == len(pending):
                summary = summarize_video_scores(
                    db.query(Shot).filter(Shot.project_id == PID).all()
                )
                elapsed = time.time() - t0
                log(f"progress summary={summary} elapsed_s={elapsed:.0f}")
        all_shots = db.query(Shot).filter(Shot.project_id == PID).all()
        summary = summarize_video_scores(all_shots)
        bands = Counter()
        for s in all_shots:
            if not (s.video_path or "").strip():
                continue
            sc = s.video_score
            if sc is None:
                bands["none"] += 1
            elif sc > 80:
                bands["good"] += 1
            elif sc >= 60:
                bands["ok"] += 1
            else:
                bands["bad"] += 1
        report = {
            "project_id": PID,
            "scored_this_run": scored,
            "errors": errors,
            "summary": summary,
            "bands": dict(bands),
            "elapsed_s": round(time.time() - t0, 1),
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"DONE {json.dumps(report, ensure_ascii=False)}")
        return 0 if not errors else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
