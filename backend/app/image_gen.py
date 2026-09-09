"""Asset image helpers: paths, prompts, clear — generation is via image_jobs enqueue."""
from __future__ import annotations

import re
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
from app.serialize import _load, serialize_asset
from app.storyboard_ops import refresh_shot_readiness

KIND_FOLDERS = {
    "character": "人物",
    "scene": "场景",
    "prop": "物品",
}

_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def kind_folder_name(kind: str) -> str:
    return KIND_FOLDERS.get(normalize_kind(kind), "物品")


def safe_asset_filename(name: str) -> str:
    cleaned = _UNSAFE_NAME.sub("_", (name or "").strip()).strip(" .")
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip("_")[:80]
    return cleaned or "asset"


def resolve_image_output_dir(project: Project) -> Path:
    raw = (getattr(project, "image_output_dir", None) or "").strip()
    if raw:
        path = Path(raw)
    else:
        path = project_dir(project.id) / "generated"
    path.mkdir(parents=True, exist_ok=True)
    for folder in KIND_FOLDERS.values():
        (path / folder).mkdir(parents=True, exist_ok=True)
    return path


def list_image_output_files(project: Project, *, kind: str | None = None) -> list[dict[str, str]]:
    """List images under 人物/场景/物品 only (no legacy per-asset_id folders)."""
    root = resolve_image_output_dir(project)
    out: list[dict[str, str]] = []
    if not root.is_dir():
        return out
    folders = [kind_folder_name(kind)] if kind else list(KIND_FOLDERS.values())
    for folder in folders:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                continue
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = f"{folder}/{path.name}"
            out.append(
                {
                    "name": path.name,
                    "rel": rel,
                    "path": str(path),
                    "folder": folder,
                }
            )
    return out


def _style_for(kind: str, project_style: str) -> str:
    blob = project_style or ""
    guofengish = any(
        x in blob for x in ("国风", "国漫", "古风", "江湖", "武侠", "仙侠")
    ) or ("3D" in blob.upper() and ("东方" in blob or "国" in blob))
    if kind == "character":
        if guofengish:
            return "guofeng_cg"
        if "动漫" in blob or "anime" in blob.lower():
            return "anime"
        return "realistic"
    if kind == "scene":
        return "guofeng" if guofengish else "scenery"
    return "guofeng" if guofengish else "product"


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


from app.domain.prop_hints import PROP_SHAPE_HINTS_ZH


def _prop_visual_brief(name: str, desc: str) -> str:
    """Keep physical props cues; drop narrative ownership / plot prose."""
    import re

    text = (desc or "").strip()
    if not text:
        return name
    # Drop clauses that describe ownership / plot usage rather than appearance.
    text = re.sub(r"[，,。；;]*[^。；;]*在[^。；;]{0,12}手中[^。；;]*", "，", text)
    text = re.sub(r"[，,。；;]*合在一起可以[^。；;]*", "，", text)
    text = re.sub(r"[，,。；;]*用于[^。；;]*", "，", text)
    text = re.sub(r"[，,。；;]*指引[^。；;]*", "，", text)
    text = re.sub(r"[，,。；;]*通往[^。；;]*", "，", text)
    text = re.sub(r"[，,。；;]*藏在[^。；;]*", "，", text)
    text = re.sub(r"[，,。；;]*里面装有[^。；;]*", "，", text)
    text = re.sub(r"[，,。；;]*记载[^。；;]*", "，", text)

    narrative = re.compile(
        r"(念想|心事|感情|帮忙|修好|砸坏|毁坏|抢走|送给|属于|曾经|后来|"
        r"被.{0,16}(?:人|的人)|"
        r"是他的|是她的|是他们的|"
        r"[\u4e00-\u9fff]{1,8}的(?:船|剑|刀|枪|佩|盒|物|琴|笛|舟))"
    )
    damage_look = re.compile(r"(裂痕|破损|裂纹|锈迹|磨损|缺口|残缺)")
    kept: list[str] = []
    for part in re.split(r"[，,。；;]+", text):
        clause = part.strip()
        if not clause:
            continue
        if narrative.search(clause):
            if damage_look.search(clause) and not re.search(
                r"(念想|帮忙|的人|是他的|是她的|[\u4e00-\u9fff]{2,8}的船)", clause
            ):
                kept.append(clause)
            continue
        kept.append(clause)
    cleaned = "，".join(kept).strip("，,。；; ")
    return cleaned or name


_PROP_SHAPE_HINTS = PROP_SHAPE_HINTS_ZH


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
            clothing = ""
            try:
                from app.services import _load

                clothing = str((_load(asset.appearance_json, {}) or {}).get("clothing") or "").strip()
            except Exception:
                clothing = ""
            clothes_lock = f"必须身着：{clothing}。" if clothing else ""
            # Do not inject asset.name — Chinese proper names have no visual signal for SDXL/Guofeng
            # and only dilute age/outfit locks.
            return (
                f"{style}。{period}。{identity}。{clothes_lock}{look}。"
                "全身站立人像，从头到脚完整入镜，正面或微侧，可见鞋子，"
                "脖子皮肤完整可见，领口自然浅阴影，不要领口黑洞，不要黑色高领中衣，"
                "纯白色不透明实底背景，不要透明，不要棋盘格，单人。"
                + (
                    "禁止白衣金甲、禁止华丽仙女战甲、禁止露出大腿的铠甲短打。"
                    if clothing and any(x in clothing for x in ("黑", "官", "布衣", "短打"))
                    else ""
                )
            )
        if field == "half":
            # Pure reframe: no look/period text that can fight the full-body reference pixels.
            return (
                "严格按参考全身图同一人物重裁为正面半身胸像："
                "五官、发型、妆造、服饰颜色与纹样必须与参考图像素级一致，"
                "禁止换脸、换年龄性别、换装、换配色或重新设计角色。"
                "头肩构图，面部清晰，不要全身。"
                "保持颈部与领口连续完整，不要脖子黑洞或黑色高领填空。"
                "纯白色不透明实底背景，不要透明，不要棋盘格。"
            )
    if kind == "scene" and field == "far":
        # Prefer visual desc over asset.name — names like「苏婆婆木屋」leak characters into empty plates.
        env = (look or "").strip() or "古风建筑与自然环境"
        return (
            f"{style}。空镜环境远景：{env}。"
            "电影布光，环境完整，远景全貌，只拍地点与建筑。"
            "禁止出现任何人、人脸、人影、剪影、手部；禁止把地点名称画成人物。"
        )
    if kind == "scene" and field == "near":
        env = (look or "").strip() or "建筑与环境材质局部"
        return (
            f"严格按参考远景图裁切放大为近景空镜局部特写，保留材质、光影与构图元素，主体：{env}。"
            "氛围连贯，只拍门窗、墙面、篱笆、器物与环境细节。"
            "禁止新增任何人、人脸、人影、剪影、手部；禁止把地点名称画成人物。"
        )
    if kind == "prop" or field == "image":
        visual = _prop_visual_brief(asset.name or "", look)
        shape = _PROP_SHAPE_HINTS.get(asset.name or "", f"单个「{asset.name}」实物道具")
        return (
            f"{style}。核心道具特写：{asset.name}。{shape}。形制细节：{visual}。"
            "单个静物居中，产品级道具质感，浅灰或纯色背景，"
            "不要人物，不要手，不要建筑外景，不要房间内景宽镜头，不要风景，"
            "不要摄影灯、聚光灯、三脚架、现代电器。"
        )
    return f"{style}。{look}"


def write_asset_image(project: Project, asset: Asset, field: str, data: bytes) -> str:
    from app.image_scores import clear_field_score

    out_root = resolve_image_output_dir(project)
    kind = normalize_kind(asset.kind)
    folder = out_root / kind_folder_name(kind)
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"{safe_asset_filename(asset.name)}_{field}.png"
    dest = folder / fname
    dest.write_bytes(data)
    mirror_dir = project_dir(project.id) / "assets" / asset.id
    mirror_dir.mkdir(parents=True, exist_ok=True)
    mirror = mirror_dir / f"{field}.png"
    mirror.write_bytes(data)
    stored = f"projects/{project.id}/assets/{asset.id}/{field}.png"
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
    clear_field_score(asset, field if field in ("half", "full", "near", "far", "image") else "image")
    return stored


def write_shot_first_frame(project: Project, shot: Any, data: bytes) -> str:
    from app.image_scores import clear_shot_first_frame_score

    out_root = resolve_image_output_dir(project)
    folder = out_root / "shots" / shot.id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "first_frame.png"
    dest.write_bytes(data)
    mirror_dir = project_dir(project.id) / "shots" / shot.id
    mirror_dir.mkdir(parents=True, exist_ok=True)
    mirror = mirror_dir / "first_frame.png"
    mirror.write_bytes(data)
    stored = f"projects/{project.id}/shots/{shot.id}/first_frame.png"
    shot.first_frame_path = stored
    clear_shot_first_frame_score(shot)
    return stored


def clear_asset_image(db: Session, project: Project, asset: Asset, field: str) -> dict[str, Any]:
    from app.image_scores import clear_field_score

    kind = normalize_kind(asset.kind)
    if kind == "character":
        if field == "half":
            asset.half_path = ""
            clear_field_score(asset, "half")
        elif field == "full":
            asset.full_path = ""
            clear_field_score(asset, "full")
        else:
            raise ValueError("人物图 field 只能是 half 或 full")
    elif kind == "scene":
        if field == "near":
            asset.near_path = ""
            clear_field_score(asset, "near")
        elif field in ("far", "image"):
            asset.far_path = ""
            clear_field_score(asset, "far")
            if field == "image":
                asset.image_path = ""
                clear_field_score(asset, "image")
        else:
            raise ValueError("场景 field 只能是 far、near 或 image")
    else:
        asset.image_path = ""
        asset.half_path = ""
        asset.full_path = ""
        clear_field_score(asset, "image")
    refresh_shot_readiness(db, project, asset_id=asset.id)
    db.commit()
    return serialize_asset(asset)


def abs_media_path(stored: str) -> Path:
    return settings.data_dir / stored


def _unlink_quiet(path: Path) -> bool:
    try:
        if path.is_file():
            path.unlink()
            return True
        if path.is_dir():
            import shutil

            shutil.rmtree(path)
            return True
    except OSError:
        pass
    return False


def delete_asset_files(project: Project, asset: Asset) -> list[str]:
    """Delete media mirrors and image_output_dir copies for this asset."""
    deleted: list[str] = []
    for rel in (
        asset.half_path,
        asset.full_path,
        getattr(asset, "far_path", "") or "",
        getattr(asset, "near_path", "") or "",
        asset.image_path,
        asset.voice_path,
    ):
        stored = (rel or "").strip()
        if not stored:
            continue
        path = abs_media_path(stored)
        if _unlink_quiet(path):
            deleted.append(str(path))
    mirror = project_dir(project.id) / "assets" / asset.id
    if _unlink_quiet(mirror):
        deleted.append(str(mirror))
    try:
        out_root = resolve_image_output_dir(project)
        folder = out_root / kind_folder_name(asset.kind)
        base = safe_asset_filename(asset.name)
        for field in ("half", "full", "far", "near", "image"):
            candidate = folder / f"{base}_{field}.png"
            if _unlink_quiet(candidate):
                deleted.append(str(candidate))
    except Exception:
        pass
    return deleted


def detach_asset_from_shots(db: Session, project_id: str, asset_id: str) -> None:
    """Clear one asset id from all shot scene/line/slot/prop refs."""
    from app.db import Shot
    from app.services import _dump, _load

    for shot in db.query(Shot).filter(Shot.project_id == project_id):
        if shot.scene_asset_id == asset_id:
            shot.scene_asset_id = ""
        slots = _load(shot.slots_json, [])
        lines = _load(shot.lines_json, [])
        props = _load(getattr(shot, "prop_asset_ids_json", None) or "[]", [])
        for slot in slots:
            if isinstance(slot, dict) and slot.get("asset_id") == asset_id:
                slot["asset_id"] = ""
        for line in lines:
            if isinstance(line, dict) and line.get("asset_id") == asset_id:
                line["asset_id"] = ""
        shot.slots_json = _dump(slots)
        shot.lines_json = _dump(lines)
        shot.prop_asset_ids_json = _dump([p for p in props if p != asset_id])


def delete_asset(db: Session, project: Project, asset: Asset) -> dict[str, Any]:
    """Delete asset row, disk files, and dangling shot refs. Caller must own session."""
    from app.db import ImageJob

    deleted_files = delete_asset_files(project, asset)
    detach_asset_from_shots(db, project.id, asset.id)
    # Drop jobs tied to this asset so the worker does not revive work.
    db.query(ImageJob).filter(ImageJob.project_id == project.id, ImageJob.asset_id == asset.id).delete(
        synchronize_session=False
    )
    aid = asset.id
    db.delete(asset)
    refresh_shot_readiness(db, project, commit=False)
    db.commit()
    return {"ok": True, "deleted_id": aid, "deleted_files": deleted_files}


def create_manual_asset(
    db: Session,
    project: Project,
    *,
    kind: str,
    name: str,
    desc_zh: str,
    appearance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a user-created asset row (no auto image generation)."""
    from app.domain.registry import ensure_character_look_trinity
    from app.serialize import _dump, _uid

    nk = normalize_kind(kind)
    if nk not in ("character", "scene", "prop"):
        raise ValueError("kind 必须是 character、scene 或 prop")
    name = (name or "").strip()
    desc_zh = (desc_zh or "").strip()
    if not name:
        raise ValueError("名称不能为空")
    if not desc_zh:
        raise ValueError("描述不能为空")
    for a in db.query(Asset).filter(Asset.project_id == project.id).all():
        if normalize_kind(a.kind) == nk and (a.name or "").strip() == name:
            raise ValueError(f"已存在同名资产：{name}")

    appearance_map = dict(appearance or {})
    age_band = ""
    refer_as = "人" if nk == "character" else ""
    if nk == "character":
        desc_zh, appearance_map, age_band = ensure_character_look_trinity(
            name=name,
            refer_as=refer_as,
            age_band=age_band,
            desc_zh=desc_zh,
            appearance=appearance_map,
        )

    asset = Asset(
        id=_uid(),
        project_id=project.id,
        kind=nk,
        name=name,
        aliases_json="[]",
        refer_as=refer_as,
        age_band=age_band,
        appearance_json=_dump(appearance_map),
        background_zh="",
        desc_zh=desc_zh,
        desc_en="",
        confirmed=True,
        created_chapter_id="",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return serialize_asset(asset)
