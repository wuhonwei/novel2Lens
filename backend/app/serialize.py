from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import Asset, Chapter, Project, Shot
from app.domain.registry import normalize_kind
from app.domain.shot_refs import build_shot_references, scene_image_path


def _uid() -> str:
    return str(uuid.uuid4())


def _load(raw: str, default: Any):
    try:
        return json.loads(raw or "") or default
    except json.JSONDecodeError:
        return default


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _effective_far_path(asset: Asset) -> str:
    far = getattr(asset, "far_path", "") or ""
    if far:
        return far
    return asset.image_path or ""


def _file_mtime_version(rel: str | None) -> int:
    rel = (rel or "").strip()
    if not rel:
        return 0
    path = Path(rel)
    if not path.is_absolute():
        path = Path(settings.data_dir) / rel
    try:
        if path.is_file():
            return int(path.stat().st_mtime)
    except OSError:
        return 0
    return 0


def _asset_media_version(asset: Asset) -> int:
    """Max mtime of stored asset images — used by UI to bust browser cache after regen."""
    fields = (
        asset.half_path,
        asset.full_path,
        getattr(asset, "far_path", "") or "",
        getattr(asset, "near_path", "") or "",
        asset.image_path,
    )
    latest = 0
    for rel in fields:
        latest = max(latest, _file_mtime_version(rel))
    return latest


def asset_ref_ready(asset: Asset) -> bool:
    """True when this book asset has the reference image(s) required for storyboard."""
    kind = normalize_kind(asset.kind)
    if kind == "character":
        return bool((asset.half_path or "").strip() and (asset.full_path or "").strip())
    if kind == "scene":
        return bool(scene_image_path(asset))
    if kind == "prop":
        return bool((asset.image_path or "").strip())
    return True


def missing_asset_image_messages(assets: list[Asset]) -> list[str]:
    out: list[str] = []
    for a in assets:
        kind = normalize_kind(a.kind)
        if asset_ref_ready(a):
            continue
        if kind == "character":
            out.append(f"人物「{a.name}」缺半身或全身图")
        elif kind == "scene":
            out.append(f"场景「{a.name}」缺参考图")
        elif kind == "prop":
            out.append(f"物品「{a.name}」缺参考图")
    return out


def require_asset_images(assets: list[Asset]) -> None:
    msgs = missing_asset_image_messages(assets)
    if msgs:
        raise ValueError("参考图未齐备，无法生成分镜：" + "；".join(msgs[:12]))


def serialize_asset(asset: Asset) -> dict[str, Any]:
    kind = normalize_kind(asset.kind)
    far_path = _effective_far_path(asset)
    near_path = getattr(asset, "near_path", "") or ""
    return {
        "id": asset.id,
        "kind": kind,
        "name": asset.name,
        "aliases": _load(asset.aliases_json, []),
        "refer_as": asset.refer_as,
        "age_band": asset.age_band,
        "appearance": _load(asset.appearance_json, {}),
        "background_zh": getattr(asset, "background_zh", "") or "",
        "desc_zh": asset.desc_zh,
        "desc_en": asset.desc_en,
        "parent_id": asset.parent_id,
        "variant_reason": asset.variant_reason,
        "confirmed": asset.confirmed,
        "half_path": asset.half_path,
        "full_path": asset.full_path,
        "far_path": far_path,
        "near_path": near_path,
        "image_path": asset.image_path,
        "voice_path": asset.voice_path,
        "image_scores": _load(getattr(asset, "image_scores_json", None) or "{}", {}),
        "media_version": _asset_media_version(asset),
        "created_chapter_id": asset.created_chapter_id,
        "portrait_ready": bool(asset.half_path and asset.full_path)
        if kind == "character"
        else bool(scene_image_path(asset) if kind == "scene" else asset.image_path),
    }


def serialize_shot(shot: Shot, chapter_title: str = "", assets: list[Asset] | None = None) -> dict[str, Any]:
    by_id = {a.id: a for a in (assets or [])}
    scene = by_id.get(shot.scene_asset_id) if shot.scene_asset_id else None
    prop_ids = _load(getattr(shot, "prop_asset_ids_json", None) or "[]", [])
    props = [by_id[pid] for pid in prop_ids if pid in by_id]
    lines = _load(shot.lines_json, [])
    slots = _load(shot.slots_json, [])
    text_fallbacks = _load(getattr(shot, "text_fallbacks_json", None) or "[]", [])
    references = (
        build_shot_references(
            scene=scene,
            lines=lines,
            slots=slots,
            props=props,
            half_lock=bool(shot.half_lock),
            assets_by_id=by_id,
            text_fallbacks=text_fallbacks,
        )
        if assets is not None
        else []
    )
    return {
        "id": shot.id,
        "chapter_id": shot.chapter_id,
        "chapter_title": chapter_title,
        "order_index": shot.order_index,
        "duration_s": shot.duration_s,
        "scene_asset_id": shot.scene_asset_id,
        "prop_asset_ids": prop_ids,
        "camera": shot.camera,
        "camera_detail": shot.camera_detail,
        "narration": shot.narration,
        "action": shot.action,
        "source_excerpt": shot.source_excerpt,
        "character_count": shot.character_count,
        "first_frame_unready": shot.first_frame_unready,
        "prompt_zh": shot.prompt_zh,
        "prompt_en": shot.prompt_en,
        "h3_prompt": shot.h3_prompt,
        "background": shot.background,
        "slots": slots,
        "text_fallbacks": text_fallbacks,
        "lines": lines,
        "half_lock": shot.half_lock,
        "first_frame_path": getattr(shot, "first_frame_path", "") or "",
        "first_frame_version": _file_mtime_version(getattr(shot, "first_frame_path", "") or ""),
        "first_frame_score": getattr(shot, "first_frame_score", None),
        "first_frame_score_comment": getattr(shot, "first_frame_score_comment", "") or "",
        "references": references,
    }


def serialize_chapter(ch: Chapter, *, include_text: bool = True) -> dict[str, Any]:
    out = {
        "id": ch.id,
        "index": ch.index,
        "title": ch.title,
        "status": ch.status,
        "used_fallback_llm": ch.used_fallback_llm,
        "last_error": ch.last_error,
        "prescan_done": ch.prescan_done,
        "text_len": len(ch.text or ""),
    }
    if include_text:
        out["text"] = ch.text
    else:
        out["text"] = ""
    return out


def serialize_project(p: Project) -> dict[str, Any]:
    return {
        "id": p.id,
        "title": p.title,
        "style": p.style,
        "llm_base_url": p.llm_base_url,
        "llm_model": p.llm_model,
        "fallback_base_url": p.fallback_base_url,
        "fallback_model": p.fallback_model,
        "allow_fallback": p.allow_fallback,
        "thinking": p.thinking,
        "zaoxiang_base_url": getattr(p, "zaoxiang_base_url", None) or "http://127.0.0.1:8000",
        "image_output_dir": getattr(p, "image_output_dir", None) or "",
        "registry_scan": _load(getattr(p, "registry_scan_json", None) or "{}", {}),
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
