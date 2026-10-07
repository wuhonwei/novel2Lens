# -*- coding: utf-8 -*-
"""Regenerate V12 shots whose video QA found unexpected/garbage speech."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import Project, SessionLocal, Shot, ensure_schema, init_db  # noqa: E402
from app.domain.prompts import ensure_h3_language_lock  # noqa: E402
from app.video_scores import clear_shot_video_score, score_shot_video  # noqa: E402

API = "http://127.0.0.1:8790"
PID = "6d9be75e-0799-4626-a646-c5036c13311a"
LOG = Path(__file__).resolve().parent / "_v12_regen_messy_audio.log"
MAX_ROUNDS = 3
AUDIO_ISSUES = {
    "unexpected_speech",
    "possible_foreign_speech",
    "missing_speech",
    "dialogue_mismatch",
}


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def messy_shots(db) -> list[Shot]:
    out = []
    for s in db.query(Shot).filter(Shot.project_id == PID).order_by(Shot.order_index).all():
        if not (s.video_path or "").strip():
            continue
        qa = json.loads(s.video_qa_json or "{}")
        issues = set(qa.get("issues") or [])
        tr = (qa.get("transcript") or "").strip()
        if issues & AUDIO_ISSUES:
            out.append(s)
        elif not qa.get("speech_expected") and len(tr) >= 4:
            out.append(s)
    return out


def refresh_h3_locks(db) -> int:
    n = 0
    for s in db.query(Shot).filter(Shot.project_id == PID).all():
        old = s.h3_prompt or ""
        new = ensure_h3_language_lock(old)
        if new != old:
            s.h3_prompt = new
            db.add(s)
            n += 1
    db.commit()
    return n


def enqueue(client: httpx.Client, shot_ids: list[str]) -> list[str]:
    job_ids = []
    for sid in shot_ids:
        r = client.post(f"/api/projects/{PID}/shots/{sid}/generate-video", params={"overwrite": "true"})
        if r.status_code != 200:
            log(f"enqueue_fail {sid} {r.status_code} {r.text[:200]}")
            continue
        job = (r.json() or {}).get("job") or {}
        jid = job.get("id")
        if jid:
            job_ids.append(jid)
            log(f"enqueued shot={sid[:8]} job={jid[:8]}")
    return job_ids


def wait_jobs(client: httpx.Client, job_ids: list[str], timeout_s: float = 7200) -> dict[str, str]:
    pending = set(job_ids)
    status: dict[str, str] = {}
    t0 = time.time()
    while pending and time.time() - t0 < timeout_s:
        r = client.get(f"/api/projects/{PID}/video-jobs", params={"active_only": "false"})
        jobs = {(j.get("id") or ""): j for j in (r.json() or {}).get("jobs") or []}
        done_now = []
        for jid in list(pending):
            j = jobs.get(jid)
            if not j:
                continue
            st = j.get("status") or ""
            if st in ("succeeded", "failed", "cancelled"):
                status[jid] = st
                done_now.append(jid)
                log(f"job {jid[:8]} -> {st} err={(j.get('error') or '')[:80]}")
        for jid in done_now:
            pending.discard(jid)
        if pending:
            time.sleep(8)
    for jid in pending:
        status[jid] = "timeout"
    return status


async def rescore(db, project: Project, shots: list[Shot]) -> None:
    for s in shots:
        db.refresh(s)
        clear_shot_video_score(s)
        db.add(s)
        db.commit()
        db.refresh(s)
        try:
            out = await score_shot_video(db, project, s, allow_regen=False)
            log(f"score shot#{s.order_index} {s.id[:8]} -> {out.get('score')} {out.get('comment')}")
        except Exception as exc:  # noqa: BLE001
            log(f"score_fail shot#{s.order_index}: {exc}")


def main() -> int:
    init_db()
    ensure_schema()
    db = SessionLocal()
    try:
        project = db.get(Project, PID)
        if not project:
            log("missing project")
            return 1
        n = refresh_h3_locks(db)
        log(f"refreshed_h3_locks={n}")
        with httpx.Client(base_url=API, timeout=120.0, trust_env=False) as client:
            for round_i in range(1, MAX_ROUNDS + 1):
                targets = messy_shots(db)
                log(f"round {round_i}: messy={len(targets)}")
                if not targets:
                    log("DONE clean")
                    return 0
                ids = [s.id for s in targets]
                job_ids = enqueue(client, ids)
                wait_jobs(client, job_ids)
                # reload shots
                shots = [db.get(Shot, sid) for sid in ids]
                shots = [s for s in shots if s]
                asyncio.run(rescore(db, project, shots))
                db.expire_all()
            left = messy_shots(db)
            log(f"DONE remaining_messy={len(left)}")
            return 0 if not left else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
