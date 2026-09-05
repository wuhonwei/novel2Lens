"""Durable image job enqueue helpers (async API surface)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import Asset, ImageJob, Project
from app.domain.registry import normalize_kind
from app.image_gen import _style_for, build_field_prompt
from app.services import _uid


ACTIVE_STATUSES = ("queued", "running")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def serialize_job(job: ImageJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "asset_id": job.asset_id,
        "kind": job.kind,
        "target_field": job.target_field,
        "status": job.status,
        "phase": job.phase or "",
        "prompt": job.prompt or "",
        "error": job.error or "",
        "batch_id": job.batch_id or "",
        "payload": json.loads(job.payload_json or "{}"),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def has_active_jobs(db: Session, project_id: str | None = None) -> bool:
    q = db.query(ImageJob).filter(ImageJob.status.in_(ACTIVE_STATUSES))
    if project_id:
        q = q.filter(ImageJob.project_id == project_id)
    return q.first() is not None


def list_active_jobs(db: Session, project_id: str, *, active_only: bool = True) -> list[dict[str, Any]]:
    q = db.query(ImageJob).filter(ImageJob.project_id == project_id)
    if active_only:
        q = q.filter(ImageJob.status.in_(ACTIVE_STATUSES))
    jobs = q.order_by(ImageJob.created_at.asc()).all()
    return [serialize_job(j) for j in jobs]


def cancel_batch(db: Session, batch_id: str) -> int:
    jobs = (
        db.query(ImageJob)
        .filter(ImageJob.batch_id == batch_id, ImageJob.status.in_(ACTIVE_STATUSES))
        .all()
    )
    n = 0
    for job in jobs:
        job.status = "cancelled"
        job.phase = ""
        job.error = "cancelled_by_user"
        job.updated_at = _utcnow()
        n += 1
    db.commit()
    return n


def mark_stale_running_failed(db: Session) -> int:
    rows = db.query(ImageJob).filter(ImageJob.status == "running").all()
    for job in rows:
        job.status = "failed"
        job.phase = ""
        job.error = "interrupted_by_restart"
        job.updated_at = _utcnow()
    db.commit()
    return len(rows)


def next_queued_job(db: Session) -> ImageJob | None:
    return (
        db.query(ImageJob)
        .filter(ImageJob.status == "queued")
        .order_by(ImageJob.created_at.asc(), ImageJob.id.asc())
        .first()
    )


def _make_job(
    *,
    project: Project,
    asset: Asset,
    kind: str,
    target_field: str,
    prompt: str,
    payload: dict[str, Any],
    batch_id: str = "",
) -> ImageJob:
    return ImageJob(
        id=_uid(),
        project_id=project.id,
        asset_id=asset.id,
        kind=kind,
        target_field=target_field,
        status="queued",
        phase="",
        prompt=prompt,
        payload_json=json.dumps(payload, ensure_ascii=False),
        error="",
        batch_id=batch_id or "",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )


def _t2i_payload(asset: Asset, project: Project, field: str, aspect: str) -> dict[str, Any]:
    kind = normalize_kind(asset.kind)
    style_key = _style_for(kind, project.style or "")
    subject = "character" if kind == "character" else ("scenery" if kind == "scene" else "prop")
    return {
        "aspect": aspect,
        "style": style_key,
        "subject_type": subject,
        "quality": "standard",
        "no_background": kind in ("character", "prop"),
    }


def _edit_payload(
    *,
    aspect: str,
    ref_field: str | None = None,
    ref_paths: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "aspect": aspect,
        "ref_field": ref_field or "",
        "ref_paths": list(ref_paths or []),
        "quality": "standard",
    }


def _build_asset_field_job(project: Project, asset: Asset, field: str) -> ImageJob:
    """Build a single queued ImageJob for one asset field (not yet added to session)."""
    kind = normalize_kind(asset.kind)
    field = (field or "").strip()
    if kind == "character":
        if field == "full":
            return _make_job(
                project=project,
                asset=asset,
                kind="t2i",
                target_field="full",
                prompt=build_field_prompt(project, asset, "full"),
                payload=_t2i_payload(asset, project, "full", "9:16"),
            )
        if field == "half":
            return _make_job(
                project=project,
                asset=asset,
                kind="edit",
                target_field="half",
                prompt=build_field_prompt(project, asset, "half"),
                payload=_edit_payload(aspect="3:4", ref_field="full"),
            )
        raise ValueError("人物图 field 只能是 half 或 full")
    if kind == "scene":
        if field == "far":
            return _make_job(
                project=project,
                asset=asset,
                kind="t2i",
                target_field="far",
                prompt=build_field_prompt(project, asset, "far"),
                payload=_t2i_payload(asset, project, "far", "16:9"),
            )
        if field == "near":
            return _make_job(
                project=project,
                asset=asset,
                kind="edit",
                target_field="near",
                prompt=build_field_prompt(project, asset, "near"),
                payload=_edit_payload(aspect="3:4", ref_field="far"),
            )
        raise ValueError("场景 field 只能是 far 或 near")
    if field not in ("", "image"):
        raise ValueError("物品 field 只能是 image")
    return _make_job(
        project=project,
        asset=asset,
        kind="t2i",
        target_field="image",
        prompt=build_field_prompt(project, asset, "image"),
        payload=_t2i_payload(asset, project, "image", "1:1"),
    )


def required_fields_for_asset(asset: Asset) -> list[str]:
    kind = normalize_kind(asset.kind)
    if kind == "character":
        return ["full", "half"]
    if kind == "scene":
        return ["far", "near"]
    return ["image"]


def enqueue_asset_field(db: Session, project: Project, asset: Asset, field: str) -> ImageJob:
    job = _build_asset_field_job(project, asset, field)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_asset_all_slots(db: Session, project: Project, asset: Asset) -> list[ImageJob]:
    """Enqueue all required slots for one asset (t2i then edit when both exist)."""
    from datetime import timedelta

    fields = required_fields_for_asset(asset)
    base_ts = _utcnow()
    jobs: list[ImageJob] = []
    for i, field in enumerate(fields):
        job = _build_asset_field_job(project, asset, field)
        job.created_at = base_ts + timedelta(microseconds=i)
        job.updated_at = job.created_at
        jobs.append(job)
        db.add(job)
    db.commit()
    for job in jobs:
        db.refresh(job)
    return jobs


def enqueue_manual_edit(
    db: Session,
    project: Project,
    asset: Asset,
    *,
    target_field: str,
    prompt: str,
    ref_paths: list[str],
    aspect: str = "3:4",
) -> ImageJob:
    if not (prompt or "").strip():
        raise ValueError("编辑提示词不能为空")
    if not ref_paths:
        raise ValueError("至少需要一张参考图")
    job = _make_job(
        project=project,
        asset=asset,
        kind="edit",
        target_field=target_field,
        prompt=prompt.strip(),
        payload=_edit_payload(aspect=aspect or "3:4", ref_paths=ref_paths),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_one_click(db: Session, project: Project) -> dict[str, Any]:
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    characters = sorted(
        [a for a in assets if normalize_kind(a.kind) == "character"],
        key=lambda a: a.name,
    )
    scenes = sorted(
        [a for a in assets if normalize_kind(a.kind) == "scene"],
        key=lambda a: a.name,
    )
    props = sorted(
        [a for a in assets if normalize_kind(a.kind) == "prop"],
        key=lambda a: a.name,
    )

    batch_id = _uid()
    jobs: list[ImageJob] = []
    base_ts = _utcnow()
    seq = 0

    def _stamp(job: ImageJob) -> ImageJob:
        nonlocal seq
        from datetime import timedelta

        job.created_at = base_ts + timedelta(microseconds=seq)
        job.updated_at = job.created_at
        seq += 1
        return job

    for asset in characters:
        prompt = build_field_prompt(project, asset, "full")
        jobs.append(
            _stamp(
                _make_job(
                    project=project,
                    asset=asset,
                    kind="t2i",
                    target_field="full",
                    prompt=prompt,
                    payload=_t2i_payload(asset, project, "full", "9:16"),
                    batch_id=batch_id,
                )
            )
        )
    for asset in scenes:
        prompt = build_field_prompt(project, asset, "far")
        jobs.append(
            _stamp(
                _make_job(
                    project=project,
                    asset=asset,
                    kind="t2i",
                    target_field="far",
                    prompt=prompt,
                    payload=_t2i_payload(asset, project, "far", "16:9"),
                    batch_id=batch_id,
                )
            )
        )
    for asset in props:
        prompt = build_field_prompt(project, asset, "image")
        jobs.append(
            _stamp(
                _make_job(
                    project=project,
                    asset=asset,
                    kind="t2i",
                    target_field="image",
                    prompt=prompt,
                    payload=_t2i_payload(asset, project, "image", "1:1"),
                    batch_id=batch_id,
                )
            )
        )
    for asset in characters:
        prompt = build_field_prompt(project, asset, "half")
        jobs.append(
            _stamp(
                _make_job(
                    project=project,
                    asset=asset,
                    kind="edit",
                    target_field="half",
                    prompt=prompt,
                    payload=_edit_payload(aspect="3:4", ref_field="full"),
                    batch_id=batch_id,
                )
            )
        )
    for asset in scenes:
        prompt = build_field_prompt(project, asset, "near")
        jobs.append(
            _stamp(
                _make_job(
                    project=project,
                    asset=asset,
                    kind="edit",
                    target_field="near",
                    prompt=prompt,
                    payload=_edit_payload(aspect="3:4", ref_field="far"),
                    batch_id=batch_id,
                )
            )
        )

    for job in jobs:
        db.add(job)
    db.commit()
    return {"batch_id": batch_id, "job_ids": [j.id for j in jobs], "jobs": [serialize_job(j) for j in jobs]}
