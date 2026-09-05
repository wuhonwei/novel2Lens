"""Resolve which asset reference images a shot needs for first-frame generation."""
from __future__ import annotations

from typing import Any


IMAGE_ROLE_ZH = {
    "scene": "核心场景参考图",
    "full": "人物全身图",
    "half": "人物半身图",
    "prop": "核心物品参考图",
}


def _path_for(asset: Any, image_key: str) -> str:
    if image_key == "half":
        return (getattr(asset, "half_path", None) or "") if asset else ""
    if image_key == "full":
        return (getattr(asset, "full_path", None) or "") if asset else ""
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
) -> dict[str, Any]:
    name = (getattr(asset, "name", None) or "").strip() if asset else ""
    path = _path_for(asset, image_key)
    role = IMAGE_ROLE_ZH.get(image_key, image_key)
    return {
        "slot_index": slot_index,
        "kind": getattr(asset, "kind", None) or ("scene" if image_key == "scene" else "character" if image_key in ("half", "full") else "prop"),
        "image_key": image_key,
        "image_role": role,
        "asset_id": asset_id or (getattr(asset, "id", None) or ""),
        "asset_name": name or "（未匹配资产）",
        "position": position or "",
        "path": path,
        "uploaded": bool(path),
        "required": required,
        "note": note,
        "status_zh": "已上传" if path else "尚未上传",
    }


def build_shot_references(
    *,
    scene: Any | None,
    lines: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    props: list[Any] | None = None,
    half_lock: bool = False,
    assets_by_id: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Ordered list of reference images for a shot (UI + readiness).

    Includes Qwen slot images (图一/二/三) plus any character half/full still
    required for readiness, and core props tied to the shot.
    """
    by_id = assets_by_id or {}
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for slot in slots:
        image_key = str(slot.get("image_key") or "")
        asset_id = str(slot.get("asset_id") or "")
        asset = by_id.get(asset_id)
        if image_key == "scene" and scene is not None:
            asset = scene
            asset_id = getattr(scene, "id", "") or asset_id
        note = ""
        if image_key == "half":
            note = "锁脸"
        elif image_key == "scene":
            note = "场景底板"
        elif image_key == "full" and half_lock:
            note = "体态服装"
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
            )
        )

    if scene is not None:
        sid = getattr(scene, "id", "") or ""
        if (sid, "scene") not in seen:
            seen.add((sid, "scene"))
            refs.insert(
                0,
                _ref(image_key="scene", asset=scene, asset_id=sid, note="本镜场景"),
            )

    for line in lines:
        asset_id = str(line.get("asset_id") or "")
        asset = by_id.get(asset_id)
        if not asset and not asset_id:
            continue
        pos = line.get("position") or ""
        for image_key, note in (("full", "体态服装"), ("half", "面部锁定")):
            key = (asset_id, image_key)
            if key in seen:
                continue
            seen.add(key)
            refs.append(
                _ref(
                    image_key=image_key,
                    asset=asset,
                    asset_id=asset_id,
                    position=pos,
                    note=note,
                    required=True,
                )
            )

    for prop in props or []:
        pid = getattr(prop, "id", "") or ""
        if not pid or (pid, "prop") in seen:
            continue
        seen.add((pid, "prop"))
        refs.append(_ref(image_key="prop", asset=prop, asset_id=pid, note="本镜核心物品"))

    return refs
