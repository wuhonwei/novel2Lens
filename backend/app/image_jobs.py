"""Durable image job enqueue helpers (async API surface)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import Asset, ImageJob, Project
from app.domain.registry import normalize_kind
from app.image_gen import _style_for, build_field_prompt, character_persona
from app.serialize import _dump, _load, _uid


ACTIVE_STATUSES = ("queued", "running")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def serialize_job(job: ImageJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "asset_id": job.asset_id or "",
        "shot_id": getattr(job, "shot_id", "") or "",
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


def _cancel_jobs(jobs: list[ImageJob]) -> int:
    n = 0
    for job in jobs:
        job.status = "cancelled"
        job.phase = ""
        job.error = "cancelled_by_user"
        job.updated_at = _utcnow()
        n += 1
    return n


def cancel_batch(db: Session, batch_id: str) -> int:
    jobs = (
        db.query(ImageJob)
        .filter(ImageJob.batch_id == batch_id, ImageJob.status.in_(ACTIVE_STATUSES))
        .all()
    )
    n = _cancel_jobs(jobs)
    db.commit()
    return n


def cancel_project_jobs(db: Session, project_id: str) -> int:
    jobs = (
        db.query(ImageJob)
        .filter(ImageJob.project_id == project_id, ImageJob.status.in_(ACTIVE_STATUSES))
        .all()
    )
    n = _cancel_jobs(jobs)
    db.commit()
    return n


def cancel_all_active_jobs(db: Session) -> int:
    """Cancel queued/running image jobs across every project (global LLM mutex)."""
    jobs = db.query(ImageJob).filter(ImageJob.status.in_(ACTIVE_STATUSES)).all()
    n = _cancel_jobs(jobs)
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
    asset: Asset | None,
    kind: str,
    target_field: str,
    prompt: str,
    payload: dict[str, Any],
    batch_id: str = "",
    shot_id: str = "",
) -> ImageJob:
    return ImageJob(
        id=_uid(),
        project_id=project.id,
        asset_id=(asset.id if asset else "") or "",
        shot_id=shot_id or "",
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
    payload: dict[str, Any] = {
        "style": style_key,
        "quality": "standard",
        "aspect": aspect,
        "subject_type": subject,
        "no_background": kind == "character",
        # Product rule: all asset T2I slots use Guofeng SDXL (not Ideogram).
        "prefer_backend": "sdxl_guofeng",
    }
    if kind == "character":
        gender, age_tier = character_persona(asset)
        payload["gender"] = gender
        payload["age_tier"] = age_tier
        if field == "full":
            payload["require_fullbody"] = True
    return payload


def _edit_payload(
    *,
    aspect: str,
    ref_field: str | None = None,
    ref_paths: list[str] | None = None,
    require_fullbody: bool = False,
    min_character_sides: int = 0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "aspect": aspect,
        "ref_field": ref_field or "",
        "ref_paths": list(ref_paths or []),
        "quality": "standard",
    }
    if require_fullbody:
        payload["require_fullbody"] = True
    if min_character_sides:
        payload["min_character_sides"] = int(min_character_sides)
    return payload


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
    from app.image_scores import clear_field_score

    clear_field_score(asset, field if field in ("half", "full", "near", "far", "image") else "image")
    job = _build_asset_field_job(project, asset, field)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_asset_all_slots(db: Session, project: Project, asset: Asset) -> list[ImageJob]:
    """Enqueue all required slots for one asset (t2i then edit when both exist)."""
    from datetime import timedelta

    from app.image_scores import clear_field_score

    fields = required_fields_for_asset(asset)
    base_ts = _utcnow()
    batch_id = _uid()
    jobs: list[ImageJob] = []
    for i, field in enumerate(fields):
        clear_field_score(asset, field if field in ("half", "full", "near", "far", "image") else "image")
        job = _build_asset_field_job(project, asset, field)
        job.batch_id = batch_id
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
    from app.image_scores import clear_field_score

    if not (prompt or "").strip():
        raise ValueError("编辑提示词不能为空")
    if not ref_paths:
        raise ValueError("至少需要一张参考图")
    clear_field_score(
        asset, target_field if target_field in ("half", "full", "near", "far", "image") else "image"
    )
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


def _shot_ref_paths(project: Project, shot, assets: list[Asset]) -> tuple[list[str], list[str], str]:
    """Return (abs_paths, labels, error). Error non-empty if unready or missing files."""
    from app.config import settings
    from app.domain.shot_refs import build_shot_references
    from app.serialize import _load

    if shot.first_frame_unready:
        return [], [], "首帧参考图未齐备"
    by_id = {a.id: a for a in assets}
    scene = by_id.get(shot.scene_asset_id) if shot.scene_asset_id else None
    prop_ids = _load(getattr(shot, "prop_asset_ids_json", None) or "[]", [])
    props = [by_id[pid] for pid in prop_ids if pid in by_id]
    refs = build_shot_references(
        scene=scene,
        lines=_load(shot.lines_json, []),
        slots=_load(shot.slots_json, []),
        props=props,
        half_lock=bool(shot.half_lock),
        assets_by_id=by_id,
        text_fallbacks=_load(getattr(shot, "text_fallbacks_json", None) or "[]", []),
    )
    paths: list[str] = []
    labels: list[str] = []
    for ref in refs:
        if ref.get("mode") == "text":
            continue
        stored = (ref.get("path") or "").strip()
        role = str(ref.get("image_role") or ref.get("asset_name") or "reference")
        # Prefer half only for single-character shots without scene/prop stacking.
        asset = by_id.get(str(ref.get("asset_id") or ""))
        char_n = int(getattr(shot, "character_count", 0) or 0)
        slot_kinds = {str(s.get("kind") or "") for s in _load(shot.slots_json, [])}
        layered = char_n >= 2 or "scene" in slot_kinds or "prop" in slot_kinds
        if (
            asset
            and normalize_kind(getattr(asset, "kind", "") or "") == "character"
            and char_n <= 1
            and not layered
        ):
            half = (getattr(asset, "half_path", None) or "").strip()
            if half:
                stored = half
                role = "人物半身图"
        if not stored:
            continue
        abs_path = settings.data_dir / stored
        if not abs_path.is_file():
            return [], [], f"缺少参考图文件: {stored}"
        from app.domain.edit_identity import edit_ref_label

        paths.append(str(abs_path))
        labels.append(edit_ref_label(asset, role, image_path=abs_path))
    if not paths:
        return [], [], "本镜没有可用参考图"
    prompt = (shot.prompt_zh or "").strip()
    if not prompt:
        return [], [], "本镜缺少首帧提示词"
    return paths, labels, ""


def _active_first_frame_job(db: Session, shot_id: str) -> ImageJob | None:
    return (
        db.query(ImageJob)
        .filter(
            ImageJob.shot_id == shot_id,
            ImageJob.target_field == "first_frame",
            ImageJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(ImageJob.created_at.desc())
        .first()
    )


def _first_frame_payload(shot, paths: list[str], labels: list[str]) -> dict[str, Any]:
    n = int(getattr(shot, "character_count", 0) or 0)
    payload: dict[str, Any] = {
        "aspect": "16:9",
        "ref_paths": paths,
        "ref_labels": labels,
        "shot_id": shot.id,
        "quality": "standard",
        "require_fullbody": True,
    }
    if n >= 2:
        payload["min_character_sides"] = min(n, 3)
    return payload


def enqueue_shot_first_frame(
    db: Session, project: Project, shot, *, batch_id: str = "", assets: list[Asset] | None = None
) -> ImageJob:
    from app.image_scores import clear_shot_first_frame_score

    assets = assets if assets is not None else db.query(Asset).filter(Asset.project_id == project.id).all()
    paths, labels, err = _shot_ref_paths(project, shot, assets)
    if err:
        raise ValueError(err)
    # Single-shot regen: cancel any prior active job for this shot, then enqueue fresh.
    prior = _active_first_frame_job(db, shot.id)
    if prior is not None:
        prior.status = "cancelled"
        prior.phase = ""
        prior.error = "superseded by re-enqueue"
        db.add(prior)
    clear_shot_first_frame_score(shot)
    payload = _first_frame_payload(shot, paths, labels)
    job = _make_job(
        project=project,
        asset=None,
        kind="edit",
        target_field="first_frame",
        prompt=shot.prompt_zh or "",
        payload=payload,
        batch_id=batch_id,
        shot_id=shot.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_chapter_first_frames(db: Session, project: Project, chapter_id: str) -> dict[str, Any]:
    from app.db import Shot
    from datetime import timedelta

    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    shots = (
        db.query(Shot)
        .filter(Shot.project_id == project.id, Shot.chapter_id == chapter_id)
        .order_by(Shot.order_index.asc())
        .all()
    )
    if not shots:
        raise ValueError("本章还没有分镜")
    batch_id = _uid()
    jobs: list[ImageJob] = []
    errors: list[str] = []
    base_ts = _utcnow()
    skipped_active = 0
    for i, shot in enumerate(shots):
        try:
            if _active_first_frame_job(db, shot.id) is not None:
                skipped_active += 1
                continue
            paths, labels, err = _shot_ref_paths(project, shot, assets)
            if err:
                errors.append(f"镜{shot.order_index}: {err}")
                continue
            payload = _first_frame_payload(shot, paths, labels)
            job = _make_job(
                project=project,
                asset=None,
                kind="edit",
                target_field="first_frame",
                prompt=shot.prompt_zh or "",
                payload=payload,
                batch_id=batch_id,
                shot_id=shot.id,
            )
            job.created_at = base_ts + timedelta(microseconds=i)
            job.updated_at = job.created_at
            jobs.append(job)
            db.add(job)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"镜{shot.order_index}: {exc}")
    if not jobs and skipped_active == 0:
        raise ValueError("没有可入队的首帧任务：" + "；".join(errors[:6]))
    if jobs:
        db.commit()
    return {
        "batch_id": batch_id,
        "queued": len(jobs),
        "skipped": len(errors) + skipped_active,
        "errors": errors,
        "jobs": [serialize_job(j) for j in jobs],
    }


def enqueue_project_first_frames(db: Session, project: Project) -> dict[str, Any]:
    from app.db import Chapter, Shot
    from datetime import timedelta

    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    chapters = db.query(Chapter).filter(Chapter.project_id == project.id).order_by(Chapter.index.asc()).all()
    shots = (
        db.query(Shot)
        .filter(Shot.project_id == project.id)
        .order_by(Shot.chapter_id.asc(), Shot.order_index.asc())
        .all()
    )
    if not shots:
        raise ValueError("项目还没有分镜")
    batch_id = _uid()
    jobs: list[ImageJob] = []
    errors: list[str] = []
    base_ts = _utcnow()
    title_by = {c.id: c.title for c in chapters}
    skipped_active = 0
    for i, shot in enumerate(shots):
        if _active_first_frame_job(db, shot.id) is not None:
            skipped_active += 1
            continue
        paths, labels, err = _shot_ref_paths(project, shot, assets)
        if err:
            errors.append(f"{title_by.get(shot.chapter_id, '')}镜{shot.order_index}: {err}")
            continue
        payload = _first_frame_payload(shot, paths, labels)
        job = _make_job(
            project=project,
            asset=None,
            kind="edit",
            target_field="first_frame",
            prompt=shot.prompt_zh or "",
            payload=payload,
            batch_id=batch_id,
            shot_id=shot.id,
        )
        job.created_at = base_ts + timedelta(microseconds=i)
        job.updated_at = job.created_at
        jobs.append(job)
        db.add(job)
    if not jobs and skipped_active == 0:
        raise ValueError("没有可入队的首帧任务：" + "；".join(errors[:8]))
    if jobs:
        db.commit()
    return {
        "batch_id": batch_id,
        "queued": len(jobs),
        "skipped": len(errors) + skipped_active,
        "errors": errors,
        "jobs": [serialize_job(j) for j in jobs],
    }
