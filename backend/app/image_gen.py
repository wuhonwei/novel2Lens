"""Generate / clear book-asset reference images via 造像."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db import Asset, Project, project_dir
from app.domain.registry import look_text, normalize_kind
from app.services import _load, refresh_shot_readiness, serialize_asset
from app.zaoxiang_client import ZaoxiangClient, ZaoxiangError


ProgressCb = Callable[[str], None]


def _client(project: Project) -> ZaoxiangClient:
    base = (getattr(project, "zaoxiang_base_url", None) or "").strip() or settings.zaoxiang_base_url
    return ZaoxiangClient(base)


def resolve_image_output_dir(project: Project) -> Path:
    raw = (getattr(project, "image_output_dir", None) or "").strip()
    if raw:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = project_dir(project.id) / "generated"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _style_for(kind: str, project_style: str) -> str:
    blob = project_style or ""
    if kind == "character":
        if any(x in blob for x in ("国风", "古风", "江湖", "武侠", "仙侠")):
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


def _write_asset_file(project: Project, asset: Asset, field: str, data: bytes) -> str:
    out_root = resolve_image_output_dir(project)
    folder = out_root / asset.id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{field}.png"
    dest.write_bytes(data)
    # Mirror under project assets so /media always works when output_dir is external
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
    else:
        asset.image_path = stored
        asset.half_path = ""
        asset.full_path = ""
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
    else:
        asset.image_path = ""
        asset.half_path = ""
        asset.full_path = ""
    refresh_shot_readiness(db, project)
    db.commit()
    return serialize_asset(asset)


def generate_character_full(project: Project, asset: Asset, client: ZaoxiangClient | None = None) -> str:
    client = client or _client(project)
    look = _look_prompt(asset)
    style = project.style or "半写实"
    prompt = (
        f"{style}。{look}。"
        "全身站立人像，从头到脚完整入镜，正面或微侧，可见鞋子，无背景白底，单人。"
    )
    job = client.create_generate(
        {
            "prompt": prompt,
            "subject_type": "character",
            "style": _style_for("character", style),
            "aspect": "9:16",
            "quality": "standard",
            "count": 1,
            "no_background": True,
            "project": f"novel2Lens-{project.id[:8]}",
        }
    )
    done = client.wait_job(job["id"])
    if (done.get("status") or "").lower() != "succeeded":
        raise ZaoxiangError(done.get("error") or f"generate failed: {done.get('status')}")
    img_id = client.first_success_image_id(done)
    data = client.download_image(img_id)
    return _write_asset_file(project, asset, "full", data)


def generate_character_half_from_full(
    project: Project, asset: Asset, client: ZaoxiangClient | None = None
) -> str:
    client = client or _client(project)
    if not asset.full_path:
        raise ValueError("需要先有全身图才能生成半身图")
    full_abs = settings.data_dir / asset.full_path
    if not full_abs.exists():
        raise ValueError(f"全身图文件不存在: {asset.full_path}")
    prompt = (
        "保持人物身份、五官、发型与服饰完全一致，生成正面半身胸像，"
        "头肩构图，面部清晰，无背景白底，不要全身。"
    )
    job = client.create_edit(
        prompt=prompt,
        image_bytes=full_abs.read_bytes(),
        filename="full.png",
        aspect="3:4",
        labels="全身参考",
        project=f"novel2Lens-{project.id[:8]}",
    )
    done = client.wait_job(job["id"])
    if (done.get("status") or "").lower() != "succeeded":
        raise ZaoxiangError(done.get("error") or f"edit failed: {done.get('status')}")
    img_id = client.first_success_image_id(done)
    data = client.download_image(img_id)
    return _write_asset_file(project, asset, "half", data)


def generate_scene_or_prop(project: Project, asset: Asset, client: ZaoxiangClient | None = None) -> str:
    client = client or _client(project)
    kind = normalize_kind(asset.kind)
    look = _look_prompt(asset)
    style = project.style or "半写实"
    if kind == "scene":
        payload = {
            "prompt": f"{style}。场景：{asset.name}。{look}。电影布光，环境完整，不要人物特写。",
            "subject_type": "scenery",
            "style": _style_for("scene", style),
            "aspect": "16:9",
            "quality": "standard",
            "count": 1,
            "no_background": False,
            "project": f"novel2Lens-{project.id[:8]}",
        }
    else:
        payload = {
            "prompt": f"{style}。物品：{asset.name}。{look}。产品级静物，居中，干净背景。",
            "subject_type": "scenery",
            "style": _style_for("prop", style),
            "aspect": "1:1",
            "quality": "standard",
            "count": 1,
            "no_background": True,
            "project": f"novel2Lens-{project.id[:8]}",
        }
    job = client.create_generate(payload)
    done = client.wait_job(job["id"])
    if (done.get("status") or "").lower() != "succeeded":
        raise ZaoxiangError(done.get("error") or f"generate failed: {done.get('status')}")
    img_id = client.first_success_image_id(done)
    data = client.download_image(img_id)
    return _write_asset_file(project, asset, "image", data)


def generate_one_asset(
    db: Session,
    project: Project,
    asset: Asset,
    *,
    field: str | None = None,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Generate images for one asset. field=None means all required slots."""
    client = _client(project)
    kind = normalize_kind(asset.kind)
    log = on_progress or (lambda _m: None)

    try:
        client.health()
    except Exception as exc:  # noqa: BLE001
        raise ZaoxiangError(f"造像服务不可用（{client.base_url}）：{exc}") from exc

    if kind == "character":
        if field in (None, "full"):
            log(f"生成全身图：{asset.name}")
            generate_character_full(project, asset, client)
        if field in (None, "half"):
            if not asset.full_path:
                log(f"生成全身图：{asset.name}")
                generate_character_full(project, asset, client)
            log(f"由全身图生成半身：{asset.name}")
            generate_character_half_from_full(project, asset, client)
    else:
        if field not in (None, "image"):
            raise ValueError("场景/物品 field 只能是 image")
        log(f"生成参考图：{asset.name}")
        generate_scene_or_prop(project, asset, client)

    refresh_shot_readiness(db, project)
    db.commit()
    return serialize_asset(asset)


def generate_all_book_images(
    db: Session,
    project: Project,
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    # characters first, then scenes, then props
    order = {"character": 0, "scene": 1, "prop": 2}
    assets = sorted(assets, key=lambda a: (order.get(normalize_kind(a.kind), 9), a.name))
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    log = on_progress or (lambda _m: None)
    for asset in assets:
        try:
            results.append(generate_one_asset(db, project, asset, on_progress=log))
        except Exception as exc:  # noqa: BLE001
            errors.append({"asset_id": asset.id, "name": asset.name, "error": str(exc)})
            log(f"失败：{asset.name} — {exc}")
    return {
        "ok": not errors,
        "generated": len(results),
        "failed": len(errors),
        "errors": errors,
        "assets": [serialize_asset(a) for a in db.query(Asset).filter(Asset.project_id == project.id).all()],
        "image_output_dir": str(resolve_image_output_dir(project)),
    }
