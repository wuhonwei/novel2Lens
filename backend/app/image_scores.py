# -*- coding: utf-8 -*-
"""Vision-LLM scoring for generated asset images and first frames."""
from __future__ import annotations

import base64
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

from sqlalchemy.orm import Session

from app.config import settings
from app.db import Asset, Project, Shot
from app.domain.registry import normalize_kind
from app.image_gen import abs_media_path, build_field_prompt
from app.llm import LLMError, OperationCancelled, chat_completion, ensure_not_cancelled, parse_json_value
from app.services import _dump, _load

SCORE_FIELDS_BY_KIND = {
    "character": ("full", "half"),
    "scene": ("far", "near"),
    "prop": ("image",),
}


def score_band(score: int | None) -> str:
    if score is None:
        return "none"
    if score > 80:
        return "good"
    if score >= 60:
        return "ok"
    return "bad"


def clamp_score(value: Any) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        n = 0
    return max(0, min(100, n))


def load_scores(asset: Asset) -> dict[str, Any]:
    data = _load(getattr(asset, "image_scores_json", None) or "{}", {})
    return data if isinstance(data, dict) else {}


def save_scores(asset: Asset, scores: dict[str, Any]) -> None:
    asset.image_scores_json = _dump(scores)


def clear_field_score(asset: Asset, field: str) -> None:
    scores = load_scores(asset)
    if field in scores:
        scores.pop(field, None)
        save_scores(asset, scores)


def set_field_score(asset: Asset, field: str, score: int, comment: str) -> dict[str, Any]:
    scores = load_scores(asset)
    entry = {
        "score": clamp_score(score),
        "comment": (comment or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    scores[field] = entry
    save_scores(asset, scores)
    return entry


def clear_shot_first_frame_score(shot: Shot) -> None:
    shot.first_frame_score = None
    shot.first_frame_score_comment = ""


def set_shot_first_frame_score(shot: Shot, score: int, comment: str) -> None:
    shot.first_frame_score = clamp_score(score)
    shot.first_frame_score_comment = (comment or "").strip()


def path_for_field(asset: Asset, field: str) -> str:
    if field == "full":
        return (asset.full_path or "").strip()
    if field == "half":
        return (asset.half_path or "").strip()
    if field == "far":
        return (getattr(asset, "far_path", "") or asset.image_path or "").strip()
    if field == "near":
        return (getattr(asset, "near_path", "") or "").strip()
    if field == "image":
        return (asset.image_path or "").strip()
    return ""


def summarize_asset_scores(assets: list[Asset], *, kind: str | None = None) -> dict[str, int]:
    counts = {"good": 0, "ok": 0, "bad": 0, "none": 0}
    for asset in assets:
        k = normalize_kind(asset.kind)
        if kind and k != kind:
            continue
        fields = SCORE_FIELDS_BY_KIND.get(k, ())
        scores = load_scores(asset)
        for field in fields:
            if not path_for_field(asset, field):
                continue
            entry = scores.get(field) if isinstance(scores.get(field), dict) else None
            sc = entry.get("score") if entry else None
            if sc is None:
                counts["none"] += 1
            else:
                counts[score_band(int(sc))] += 1
    return counts


def summarize_shot_scores(shots: list[Shot]) -> dict[str, int]:
    counts = {"good": 0, "ok": 0, "bad": 0, "none": 0}
    for shot in shots:
        if not (getattr(shot, "first_frame_path", "") or "").strip():
            continue
        sc = getattr(shot, "first_frame_score", None)
        if sc is None:
            counts["none"] += 1
        else:
            counts[score_band(int(sc))] += 1
    return counts


def _image_data_url(path: Path) -> str:
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def score_image_file(
    *,
    image_path: Path,
    brief: str,
    base_url: str | None = None,
    model: str | None = None,
    chat: Callable[..., Awaitable[str]] | None = None,
    is_cancelled=None,
) -> dict[str, Any]:
    if not image_path.is_file():
        raise FileNotFoundError(str(image_path))
    await ensure_not_cancelled(is_cancelled)
    base = (base_url or settings.vision_llm_base_url).rstrip("/")
    model_name = model or settings.vision_llm_model
    data_url = _image_data_url(image_path)
    system = (
        "你是影视分镜参考图质检员。根据用户给出的「生成意图」评价图片是否达标。"
        "只输出一个 JSON 对象：{\"score\":0到100的整数,\"comment\":\"一两句中文评语\"}。"
        "评分标准：身份/主体是否正确、服饰或场景是否符合、构图是否匹配、画风是否一致。"
        "不要只凭好看打高分；明显跑题必须低于60。"
    )
    user_text = f"生成意图：\n{(brief or '').strip() or '（无提示词）'}\n请打分并简评。"
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    runner = chat or chat_completion
    text = await runner(
        base_url=base,
        model=model_name,
        messages=messages,
        temperature=0.1,
        timeout=180.0,
        is_cancelled=is_cancelled,
    )
    data = parse_json_value(text)
    if not isinstance(data, dict):
        raise LLMError("视觉模型未返回对象 JSON")
    return {
        "score": clamp_score(data.get("score")),
        "comment": str(data.get("comment") or data.get("reason") or "").strip()[:500],
    }


async def score_project_images(
    db: Session,
    project: Project,
    *,
    scope: str = "assets",
    kind: str | None = None,
    chat: Callable[..., Awaitable[str]] | None = None,
    is_cancelled=None,
) -> dict[str, Any]:
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    shots = db.query(Shot).filter(Shot.project_id == project.id).order_by(Shot.order_index.asc()).all()
    scored = 0
    errors: list[str] = []
    cancelled = False

    if scope in ("assets", "all"):
        for asset in assets:
            k = normalize_kind(asset.kind)
            if kind and k != kind:
                continue
            for field in SCORE_FIELDS_BY_KIND.get(k, ()):
                try:
                    await ensure_not_cancelled(is_cancelled)
                except OperationCancelled:
                    cancelled = True
                    break
                stored = path_for_field(asset, field)
                if not stored:
                    continue
                abs_path = abs_media_path(stored)
                if not abs_path.is_file():
                    errors.append(f"{asset.name}/{field}: 文件缺失")
                    continue
                brief = build_field_prompt(project, asset, field)
                try:
                    result = await score_image_file(
                        image_path=abs_path, brief=brief, chat=chat, is_cancelled=is_cancelled
                    )
                    set_field_score(asset, field, result["score"], result["comment"])
                    scored += 1
                    db.commit()
                except OperationCancelled:
                    cancelled = True
                    break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{asset.name}/{field}: {exc}")
            if cancelled:
                break

    if not cancelled and scope in ("shots", "all"):
        for shot in shots:
            try:
                await ensure_not_cancelled(is_cancelled)
            except OperationCancelled:
                cancelled = True
                break
            stored = (getattr(shot, "first_frame_path", "") or "").strip()
            if not stored:
                continue
            abs_path = abs_media_path(stored)
            if not abs_path.is_file():
                errors.append(f"镜{shot.order_index}: 文件缺失")
                continue
            brief = (shot.prompt_zh or "").strip() or "分镜首帧"
            try:
                result = await score_image_file(
                    image_path=abs_path, brief=brief, chat=chat, is_cancelled=is_cancelled
                )
                set_shot_first_frame_score(shot, result["score"], result["comment"])
                scored += 1
                db.commit()
            except OperationCancelled:
                cancelled = True
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"镜{shot.order_index}: {exc}")

    if cancelled:
        raise OperationCancelled("cancelled_by_user")

    kind_counts = summarize_asset_scores(assets, kind=kind) if scope in ("assets", "all") else None
    shot_counts = summarize_shot_scores(shots) if scope in ("shots", "all") else None
    return {
        "ok": True,
        "scored": scored,
        "errors": errors,
        "asset_counts": kind_counts,
        "shot_counts": shot_counts,
    }
