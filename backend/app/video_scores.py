"""Persist and run post-hoc video QA (keyframes + ASR vs h3_prompt)."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db import Project, Shot, project_dir
from app.domain.video_speech import (
    combine_video_scores,
    extract_expected_speech,
    score_transcript,
    speech_expected,
)
from app.image_gen import abs_media_path
from app.image_scores import clamp_score, score_image_file
from app.llm import OperationCancelled, ensure_not_cancelled
from app.serialize import _dump, _load
from app.video_qa import asr_available, extract_keyframes, extract_wav, transcribe_wav

log = logging.getLogger(__name__)


def clear_shot_video_score(shot: Shot) -> None:
    shot.video_score = None
    shot.video_score_comment = ""
    shot.video_qa_json = "{}"


def set_shot_video_score(
    shot: Shot,
    score: int,
    comment: str,
    qa: dict[str, Any] | None = None,
) -> None:
    shot.video_score = clamp_score(score)
    shot.video_score_comment = (comment or "").strip()[:500]
    payload = dict(qa or {})
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    shot.video_qa_json = _dump(payload)


def summarize_video_scores(shots: list[Shot]) -> dict[str, int]:
    from app.image_scores import score_band

    counts = {"good": 0, "ok": 0, "bad": 0, "none": 0}
    for shot in shots:
        if not (getattr(shot, "video_path", "") or "").strip():
            continue
        sc = getattr(shot, "video_score", None)
        if sc is None:
            counts["none"] += 1
        else:
            counts[score_band(int(sc))] += 1
    return counts


def _build_comment(
    *,
    visual: int | None,
    audio: int | None,
    issues: list[str],
    speech_on: bool,
    audio_skipped: bool,
) -> str:
    parts: list[str] = []
    if visual is not None:
        parts.append(f"画面{visual}")
    if audio_skipped:
        parts.append("声音未检(无ASR)")
    elif audio is not None:
        parts.append(f"声音{audio}")
    if "missing_speech" in issues:
        parts.append("应有台词但听写为空")
    elif "dialogue_mismatch" in issues:
        parts.append("台词匹配偏弱")
    elif "unexpected_speech" in issues:
        parts.append("静音镜却检出人声")
    elif "possible_foreign_speech" in issues:
        parts.append("疑似外语人声")
    if not parts:
        return "已评估"
    return "；".join(parts)


async def score_shot_video(
    db: Session,
    project: Project,
    shot: Shot,
    *,
    chat: Callable[..., Awaitable[str]] | None = None,
    is_cancelled=None,
    allow_regen: bool = True,
) -> dict[str, Any]:
    rel = (shot.video_path or "").strip()
    prompt = (shot.h3_prompt or "").strip()
    if not rel:
        raise ValueError("本镜尚无视频")
    if not prompt:
        raise ValueError("本镜缺少 H3 提示词")
    video = abs_media_path(rel)
    if not video.is_file():
        raise FileNotFoundError(str(video))

    await ensure_not_cancelled(is_cancelled)
    work = project_dir(project.id) / "shots" / shot.id / "_video_qa"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    lines = _load(shot.lines_json or "[]", [])
    expected = extract_expected_speech(
        prompt, lines=lines if isinstance(lines, list) else [], narration=shot.narration or ""
    )
    need_speech = speech_expected(expected)

    frames = extract_keyframes(video, work / "frames", count=settings.video_qa_frame_count)
    frame_scores: list[dict[str, Any]] = []
    for fp in frames:
        await ensure_not_cancelled(is_cancelled)
        one = await score_image_file(
            image_path=fp,
            brief=prompt,
            chat=chat,
            is_cancelled=is_cancelled,
        )
        frame_scores.append(
            {
                "path": fp.name,
                "score": one["score"],
                "comment": one.get("comment") or "",
            }
        )
    visual = int(round(sum(f["score"] for f in frame_scores) / max(1, len(frame_scores))))

    audio_skipped = False
    transcript = ""
    audio_score: int | None = None
    audio_issues: list[str] = []
    try:
        wav = extract_wav(video, work / "audio.wav")
        if asr_available():
            transcript = transcribe_wav(wav)
            audio_out = score_transcript(expected, transcript)
            audio_score = int(audio_out["score"])
            audio_issues = list(audio_out.get("issues") or [])
        else:
            audio_skipped = True
    except Exception as exc:
        log.exception("video audio QA failed for %s", shot.id)
        audio_skipped = True
        audio_issues = [f"audio_error:{type(exc).__name__}"]

    combined = combine_video_scores(visual, audio_score, speech_expected=need_speech)
    issues = list(audio_issues)
    comment = _build_comment(
        visual=visual,
        audio=audio_score,
        issues=issues,
        speech_on=need_speech,
        audio_skipped=audio_skipped or audio_score is None,
    )
    qa = {
        "visual_score": visual,
        "audio_score": audio_score,
        "weights": combined["weights"],
        "expected_speech": expected,
        "transcript": transcript[:800],
        "speech_expected": need_speech,
        "frames": frame_scores,
        "issues": issues,
        "model_vision": settings.vision_llm_model,
        "model_asr": settings.video_qa_asr_model if not audio_skipped else "",
        "audio_skipped": audio_skipped,
        "regen_count": int((_load(shot.video_qa_json or "{}", {}) or {}).get("regen_count") or 0),
    }
    set_shot_video_score(shot, combined["score"], comment, qa)
    db.add(shot)
    db.commit()
    db.refresh(shot)

    regen = False
    if (
        allow_regen
        and settings.video_qa_auto_regen
        and combined["score"] < int(settings.video_qa_regen_threshold)
        and int(qa["regen_count"]) < int(settings.video_qa_max_regen)
    ):
        from app.video_jobs import enqueue_shot_video

        qa["regen_count"] = int(qa["regen_count"]) + 1
        set_shot_video_score(shot, combined["score"], comment + "；已触发自动重生成", qa)
        db.add(shot)
        db.commit()
        enqueue_shot_video(db, project, shot, overwrite=True)
        regen = True

    return {
        "shot_id": shot.id,
        "score": shot.video_score,
        "comment": shot.video_score_comment,
        "qa": qa,
        "regen": regen,
    }


async def score_project_videos(
    db: Session,
    project: Project,
    *,
    scope: str = "chapter",
    chapter_id: str | None = None,
    shot_id: str | None = None,
    chat: Callable[..., Awaitable[str]] | None = None,
    is_cancelled=None,
) -> dict[str, Any]:
    q = db.query(Shot).filter(Shot.project_id == project.id)
    if scope == "shot":
        if not shot_id:
            raise ValueError("scope=shot 需要 shot_id")
        q = q.filter(Shot.id == shot_id)
    elif scope == "chapter":
        if not chapter_id:
            raise ValueError("scope=chapter 需要 chapter_id")
        q = q.filter(Shot.chapter_id == chapter_id)
    elif scope != "project":
        raise ValueError("scope 必须是 shot、chapter 或 project")

    shots = q.order_by(Shot.order_index.asc()).all()
    scored = 0
    errors: list[str] = []
    skipped: list[dict[str, str]] = []
    cancelled = False
    for shot in shots:
        try:
            await ensure_not_cancelled(is_cancelled)
        except OperationCancelled:
            cancelled = True
            break
        if not (shot.video_path or "").strip():
            skipped.append({"shot_id": shot.id, "reason": "no_video"})
            continue
        if not (shot.h3_prompt or "").strip():
            skipped.append({"shot_id": shot.id, "reason": "no_h3_prompt"})
            continue
        try:
            await score_shot_video(
                db,
                project,
                shot,
                chat=chat,
                is_cancelled=is_cancelled,
                allow_regen=True,
            )
            scored += 1
        except OperationCancelled:
            cancelled = True
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{shot.id[:8]}: {exc}")
            log.exception("score video failed %s", shot.id)
    return {
        "ok": True,
        "scored": scored,
        "errors": errors,
        "skipped": skipped,
        "cancelled": cancelled,
        "summary": summarize_video_scores(
            db.query(Shot).filter(Shot.project_id == project.id).all()
        ),
    }


def schedule_score_after_video(project_id: str, shot_id: str) -> None:
    """Fire-and-forget score after VideoWorker success (daemon thread)."""
    if not settings.video_qa_auto_after_video:
        return
    import threading

    def _run() -> None:
        import asyncio

        from app.db import SessionLocal

        db = SessionLocal()
        try:
            project = db.get(Project, project_id)
            shot = db.get(Shot, shot_id)
            if not project or not shot:
                return
            asyncio.run(score_shot_video(db, project, shot, allow_regen=True))
        except Exception:
            log.exception("auto video QA failed project=%s shot=%s", project_id, shot_id)
        finally:
            db.close()

    threading.Thread(target=_run, name=f"video-qa-{shot_id[:8]}", daemon=True).start()
