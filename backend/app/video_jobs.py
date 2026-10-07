"""Durable H3 video job enqueue helpers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import Project, Shot, VideoJob
from app.serialize import _uid

ACTIVE_STATUSES = ("queued", "running")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def serialize_video_job(job: VideoJob) -> dict[str, Any]:
    try:
        payload = json.loads(job.payload_json or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": job.id,
        "project_id": job.project_id,
        "shot_id": job.shot_id or "",
        "status": job.status,
        "phase": job.phase or "",
        "prompt": job.prompt or "",
        "error": job.error or "",
        "batch_id": job.batch_id or "",
        "payload": payload,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def has_active_video_jobs(db: Session, project_id: str | None = None) -> bool:
    q = db.query(VideoJob).filter(VideoJob.status.in_(ACTIVE_STATUSES))
    if project_id:
        q = q.filter(VideoJob.project_id == project_id)
    return q.first() is not None


def list_video_jobs(db: Session, project_id: str, *, active_only: bool = True) -> list[dict[str, Any]]:
    q = db.query(VideoJob).filter(VideoJob.project_id == project_id)
    if active_only:
        q = q.filter(VideoJob.status.in_(ACTIVE_STATUSES))
    jobs = q.order_by(VideoJob.created_at.asc()).all()
    return [serialize_video_job(j) for j in jobs]


def _cancel_jobs(jobs: list[VideoJob]) -> int:
    n = 0
    for job in jobs:
        job.status = "cancelled"
        job.phase = ""
        job.error = "cancelled_by_user"
        job.updated_at = _utcnow()
        n += 1
    return n


def cancel_project_video_jobs(db: Session, project_id: str) -> int:
    jobs = (
        db.query(VideoJob)
        .filter(VideoJob.project_id == project_id, VideoJob.status.in_(ACTIVE_STATUSES))
        .all()
    )
    n = _cancel_jobs(jobs)
    db.commit()
    return n


def cancel_all_active_video_jobs(db: Session) -> int:
    jobs = db.query(VideoJob).filter(VideoJob.status.in_(ACTIVE_STATUSES)).all()
    n = _cancel_jobs(jobs)
    db.commit()
    return n


def mark_stale_video_running_failed(db: Session) -> int:
    rows = db.query(VideoJob).filter(VideoJob.status == "running").all()
    for job in rows:
        job.status = "failed"
        job.phase = ""
        job.error = "interrupted_by_restart"
        job.updated_at = _utcnow()
    db.commit()
    return len(rows)


def next_queued_video_job(db: Session) -> VideoJob | None:
    return (
        db.query(VideoJob)
        .filter(VideoJob.status == "queued")
        .order_by(VideoJob.created_at.asc(), VideoJob.id.asc())
        .first()
    )


def _active_video_job_for_shot(db: Session, shot_id: str) -> VideoJob | None:
    return (
        db.query(VideoJob)
        .filter(VideoJob.shot_id == shot_id, VideoJob.status.in_(ACTIVE_STATUSES))
        .order_by(VideoJob.created_at.desc())
        .first()
    )


def _shot_ready_for_video(shot: Shot) -> None:
    if not (getattr(shot, "first_frame_path", "") or "").strip():
        raise ValueError("本镜尚无首帧，请先生成首帧")
    if not (getattr(shot, "h3_prompt", "") or "").strip():
        raise ValueError("本镜缺少 H3 运镜提示词")


def enqueue_shot_video(
    db: Session,
    project: Project,
    shot: Shot,
    *,
    batch_id: str = "",
    overwrite: bool = True,
    aspect: str = "16:9",
    clarity: str = "0.75",
    turbo: bool = True,
) -> VideoJob:
    _shot_ready_for_video(shot)
    if not overwrite and (getattr(shot, "video_path", "") or "").strip():
        raise ValueError("本镜已有视频；如需覆盖请传 overwrite=true")
    existing = _active_video_job_for_shot(db, shot.id)
    if existing:
        raise ValueError("本镜视频任务进行中")

    from app.video_scores import clear_shot_video_score

    clear_shot_video_score(shot)
    db.add(shot)

    duration = float(shot.duration_s or 6.0)
    payload = {
        "shot_id": shot.id,
        "aspect": aspect,
        "clarity": clarity,
        "turbo": bool(turbo),
        "duration_s": duration,
        "first_frame_path": shot.first_frame_path,
    }
    job = VideoJob(
        id=_uid(),
        project_id=project.id,
        shot_id=shot.id,
        status="queued",
        phase="",
        prompt=(shot.h3_prompt or "").strip(),
        payload_json=json.dumps(payload, ensure_ascii=False),
        error="",
        batch_id=batch_id or "",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_chapter_videos(
    db: Session,
    project: Project,
    chapter_id: str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    shots = (
        db.query(Shot)
        .filter(Shot.project_id == project.id, Shot.chapter_id == chapter_id)
        .order_by(Shot.order_index.asc())
        .all()
    )
    batch_id = _uid()
    jobs: list[VideoJob] = []
    skipped: list[dict[str, str]] = []
    for shot in shots:
        if not overwrite and (getattr(shot, "video_path", "") or "").strip():
            skipped.append({"shot_id": shot.id, "reason": "already_has_video"})
            continue
        try:
            _shot_ready_for_video(shot)
        except ValueError as exc:
            skipped.append({"shot_id": shot.id, "reason": str(exc)})
            continue
        if _active_video_job_for_shot(db, shot.id):
            skipped.append({"shot_id": shot.id, "reason": "already_queued"})
            continue
        jobs.append(
            enqueue_shot_video(
                db,
                project,
                shot,
                batch_id=batch_id,
                overwrite=True,
            )
        )
    return {
        "batch_id": batch_id if jobs else "",
        "job_ids": [j.id for j in jobs],
        "queued": len(jobs),
        "skipped": skipped,
        "jobs": [serialize_video_job(j) for j in jobs],
    }
