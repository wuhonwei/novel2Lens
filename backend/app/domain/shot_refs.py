"""Resolve which asset reference images a shot needs for first-frame generation."""
from __future__ import annotations

from typing import Any

from app.domain.slots import normalize_portrait_key

IMAGE_ROLE_ZH = {
    "scene": "核心场景参考图",
    "full": "人物全身图",
    "half": "人物半身图",
    "prop": "核心物品参考图",
}


def scene_image_path(asset: Any) -> str:
    if not asset:
        return ""
    near = getattr(asset, "near_path", None) or ""
    if near:
        return near.strip()
    far = getattr(asset, "far_path", None) or ""
    if far:
        return far.strip()
    return (getattr(asset, "image_path", None) or "").strip()


def _path_for(asset: Any, image_key: str) -> str:
    if image_key == "half":
        return (getattr(asset, "half_path", None) or "") if asset else ""
    if image_key == "full":
        return (getattr(asset, "full_path", None) or "") if asset else ""
    if image_key == "scene":
        return scene_image_path(asset)
    return (getattr(asset, "image_path", None) or "") if asset else ""


def _ref(
    *,
    image_key: str,
    asset: Any | None,
    asset_id: str = "",
    slot_index: int | None = None,
    position: str | None = None,
    note: str = "",
    required: bool = True,
    mode: str = "image",
    text: str = "",
) -> dict[str, Any]:
    name = (getattr(asset, "name", None) or "").strip() if asset else ""
    path = _path_for(asset, image_key) if mode == "image" else ""
    role = IMAGE_ROLE_ZH.get(image_key, image_key)
    if mode == "text":
        status = "文字描述补足"
        uploaded = True  # not blocking image upload for text-only refs
    else:
        status = "已上传" if path else "尚未上传"
        uploaded = bool(path)
    return {
        "slot_index": slot_index,
        "kind": getattr(asset, "kind", None)
        or ("scene" if image_key == "scene" else "character" if image_key in ("half", "full") else "prop"),
        "image_key": image_key,
        "image_role": role,
        "asset_id": asset_id or (getattr(asset, "id", None) or ""),
        "asset_name": name or "（未匹配资产）",
        "position": position or "",
        "path": path,
        "uploaded": uploaded,
        "required": required and mode == "image",
        "note": note,
        "status_zh": status,
        "mode": mode,
        "text": text,
    }


def build_shot_references(
    *,
    scene: Any | None,
    lines: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    props: list[Any] | None = None,
    half_lock: bool = False,
    assets_by_id: dict[str, Any] | None = None,
    text_fallbacks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Image slots (≤3) plus text-fallback assets that did not get a slot."""
    del half_lock
    del lines
    del props
    del scene
    by_id = assets_by_id or {}
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for slot in slots:
        image_key = str(slot.get("image_key") or "")
        asset_id = str(slot.get("asset_id") or "")
        asset = by_id.get(asset_id)
        if image_key in ("half", "full"):
            image_key = normalize_portrait_key(image_key)
        note = ""
        if image_key == "half":
            note = "本镜用半身"
        elif image_key == "full":
            note = "本镜用全身"
        elif image_key == "scene":
            note = "场景底板"
        elif image_key == "prop":
            note = "本镜核心物品"
        key = (asset_id, image_key)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            _ref(
                image_key=image_key,
                asset=asset,
                asset_id=asset_id,
                slot_index=int(slot["index"]) if slot.get("index") is not None else None,
                position=slot.get("position") or "",
                note=note,
                mode="image",
            )
        )

    for fb in text_fallbacks or []:
        image_key = str(fb.get("image_key") or "")
        asset_id = str(fb.get("asset_id") or "")
        key = (asset_id, image_key or fb.get("kind") or "text")
        if key in seen:
            continue
        seen.add(key)
        asset = by_id.get(asset_id)
        refs.append(
            _ref(
                image_key=image_key or ("scene" if fb.get("kind") == "scene" else "prop"),
                asset=asset,
                asset_id=asset_id,
                position=fb.get("position") or "",
                note=fb.get("note") or "文字描述补足",
                required=False,
                mode="text",
                text=fb.get("text") or "",
            )
        )

    return refs
