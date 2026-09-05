"""Asset image helpers: paths, prompts, clear — generation is via image_jobs enqueue."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db import Asset, Project, project_dir
from app.domain.registry import look_text, normalize_kind
from app.comfy_pipeline.persona import (
    identity_lock_en,
    identity_lock_zh,
    identity_negative,
    infer_age_tier,
    infer_gender,
)
from app.services import _load, refresh_shot_readiness, serialize_asset


def resolve_image_output_dir(project: Project) -> Path:
    raw = (getattr(project, "image_output_dir", None) or "").strip()
    if raw:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = project_dir(project.id) / "generated"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_image_output_files(project: Project) -> list[dict[str, str]]:
    root = resolve_image_output_dir(project)
    out: list[dict[str, str]] = []
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = path.name
            out.append({"name": path.name, "rel": rel, "path": str(path)})
    return out


def _style_for(kind: str, project_style: str) -> str:
    blob = project_style or ""
    if kind == "character":
        if any(x in blob for x in ("国风", "古风", "江湖", "武侠", "仙侠")) or (
            "3D" in blob.upper() and ("东方" in blob or "国" in blob)
        ):
            return "guofeng_cg"
        if "动漫" in blob or "anime" in blob.lower():
            return "anime"
        return "realistic"
    if kind == "scene":
        return "scenery"
    return "product"


def _look_prompt(asset: Asset) -> str:
    kind = normalize_kind(asset.kind)
    if kind == "character":
        text = look_text({"desc_zh": asset.desc_zh, "appearance": _load(asset.appearance_json, {})})
    else:
        text = (asset.desc_zh or "").strip()
    return text or asset.name


def character_persona(asset: Asset) -> tuple[str, str]:
    look = _look_prompt(asset)
    gender = infer_gender(
        name=asset.name or "",
        refer_as=asset.refer_as or "",
        age_band=asset.age_band or "",
        look=look,
    )
    age_tier = infer_age_tier(
        name=asset.name or "",
        refer_as=asset.refer_as or "",
        age_band=asset.age_band or "",
        look=look,
    )
    return gender, age_tier


def build_field_prompt(project: Project, asset: Asset, field: str) -> str:
    kind = normalize_kind(asset.kind)
    look = _look_prompt(asset)
    style = project.style or "半写实"
    if kind == "character":
        gender, age_tier = character_persona(asset)
        lock = identity_lock_zh(
            gender=gender,
            age_tier=age_tier,
            refer_as=asset.refer_as or "",
            age_band=asset.age_band or "",
        )
        en = identity_lock_en(gender=gender, age_tier=age_tier)
        identity = "。".join(x for x in (lock, en) if x)
        style_key = _style_for("character", style)
        period = ""
        if style_key == "guofeng_cg":
            period = (
                "国风三维角色，古装/汉服或江湖劲装，东方古代服饰纹样，"
                "不要现代衬衫西裤运动鞋，不要真人摄影棚写真"
            )
        if field == "full":
            return (
                f"{style}。{period}。{identity}。角色名：{asset.name}。{look}。"
                "全身站立人像，从头到脚完整入镜，正面或微侧，可见鞋子，无背景白底，单人。"
            )
        if field == "half":
            return (
                f"保持人物身份、性别、年龄感、五官、发型与服饰完全一致（{identity}），"
                f"{period}。"
                "生成正面半身胸像，头肩构图，面部清晰，无背景白底，不要全身。"
            )
    if kind == "scene" and field == "far":
        return f"{style}。场景：{asset.name}。{look}。电影布光，环境完整，远景全貌，不要人物特写。"
    if kind == "scene" and field == "near":
        return (
            f"保持场景气质与构图元素一致，生成近景局部特写：{asset.name}。"
            f"{look}。氛围连贯，不要出现无关人物。"
        )
    if kind == "prop" or field == "image":
        return f"{style}。物品：{asset.name}。{look}。产品级静物，居中，干净背景。"
    return f"{style}。{look}"


def write_asset_image(project: Project, asset: Asset, field: str, data: bytes) -> str:
    out_root = resolve_image_output_dir(project)
    folder = out_root / asset.id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{field}.png"
    dest.write_bytes(data)
    mirror_dir = project_dir(project.id) / "assets" / asset.id
    mirror_dir.mkdir(parents=True, exist_ok=True)
    mirror = mirror_dir / f"{field}.png"
    mirror.write_bytes(data)
    stored = f"projects/{project.id}/assets/{asset.id}/{field}.png"
    kind = normalize_kind(asset.kind)
    if kind == "character":
        if field == "half":
            asset.half_path = stored
        elif field == "full":
            asset.full_path = stored
        else:
            asset.image_path = stored
    elif kind == "scene":
        if field == "near":
            asset.near_path = stored
        else:
            # far (default) + legacy image
            asset.far_path = stored
            if field == "image" or not asset.image_path:
                asset.image_path = stored
    else:
        asset.image_path = stored
    return stored


def clear_asset_image(db: Session, project: Project, asset: Asset, field: str) -> dict[str, Any]:
    kind = normalize_kind(asset.kind)
    if kind == "character":
        if field == "half":
            asset.half_path = ""
        elif field == "full":
            asset.full_path = ""
        else:
            raise ValueError("人物图 field 只能是 half 或 full")
    elif kind == "scene":
        if field == "near":
            asset.near_path = ""
        elif field in ("far", "image"):
            asset.far_path = ""
            if field == "image":
                asset.image_path = ""
        else:
            raise ValueError("场景 field 只能是 far、near 或 image")
    else:
        asset.image_path = ""
        asset.half_path = ""
        asset.full_path = ""
    refresh_shot_readiness(db, project)
    db.commit()
    return serialize_asset(asset)


def abs_media_path(stored: str) -> Path:
    return settings.data_dir / stored
