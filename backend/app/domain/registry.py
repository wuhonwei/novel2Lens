from __future__ import annotations

from typing import Any


KIND_ALIASES = {
    "character": "character",
    "char": "character",
    "person": "character",
    "people": "character",
    "角色": "character",
    "人物": "character",
    "人名": "character",
    "scene": "scene",
    "location": "scene",
    "place": "scene",
    "场景": "scene",
    "地点": "scene",
    "场所": "scene",
    "prop": "prop",
    "item": "prop",
    "object": "prop",
    "物品": "prop",
    "道具": "prop",
    "信物": "prop",
}


def normalize_kind(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return "prop"
    if key in KIND_ALIASES:
        return KIND_ALIASES[key]
    # Chinese keys are case-sensitive in map above via exact; try original strip
    key_cn = (raw or "").strip()
    return KIND_ALIASES.get(key_cn, KIND_ALIASES.get(key, "prop"))


def _uniq_aliases(values: list[Any]) -> list[str]:
    out: list[str] = []
    for v in values:
        s = str(v or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def merge_registry_entry(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged["kind"] = normalize_kind(incoming.get("kind") or existing.get("kind"))
    if incoming.get("name"):
        merged["name"] = str(incoming["name"]).strip()
    aliases = list(existing.get("aliases") or [])
    aliases.extend(incoming.get("aliases") or [])
    if incoming.get("name") and incoming["name"] != existing.get("name"):
        aliases.append(incoming["name"])
    merged["aliases"] = _uniq_aliases(aliases)
    if incoming.get("refer_as") and not (existing.get("refer_as") or "").strip():
        merged["refer_as"] = incoming["refer_as"]
    elif incoming.get("refer_as"):
        merged["refer_as"] = incoming["refer_as"]
    if incoming.get("age_band") and not (existing.get("age_band") or "").strip():
        merged["age_band"] = incoming["age_band"]
    elif incoming.get("age_band"):
        merged["age_band"] = incoming["age_band"]

    appearance = dict(existing.get("appearance") or {})
    for key, value in (incoming.get("appearance") or {}).items():
        if value in (None, ""):
            continue
        if key not in appearance or not appearance.get(key):
            appearance[key] = value
        else:
            appearance[key] = value
    merged["appearance"] = appearance

    desc_zh = (existing.get("desc_zh") or "").strip()
    add_zh = (incoming.get("desc_zh") or incoming.get("notes") or "").strip()
    if add_zh:
        if not desc_zh:
            merged["desc_zh"] = add_zh
        elif add_zh not in desc_zh:
            merged["desc_zh"] = f"{desc_zh}；{add_zh}"
        else:
            merged["desc_zh"] = desc_zh
    desc_en = (existing.get("desc_en") or "").strip()
    add_en = (incoming.get("desc_en") or "").strip()
    if add_en and not desc_en:
        merged["desc_en"] = add_en
    elif add_en and add_en not in desc_en:
        merged["desc_en"] = f"{desc_en}; {add_en}"
    return merged


def _entry_incomplete(asset: dict[str, Any]) -> dict[str, Any] | None:
    kind = normalize_kind(asset.get("kind"))
    name = (asset.get("name") or "").strip()
    if not name:
        return {"name": name or "?", "kind": kind, "reason": "缺少名称"}
    desc = (asset.get("desc_zh") or asset.get("notes") or "").strip()
    appearance = asset.get("appearance") or {}
    has_look = bool(desc) or any(bool(v) for v in appearance.values())
    if kind == "character" and not has_look:
        return {"name": name, "kind": kind, "reason": "缺少外貌/衣着描述"}
    if kind in ("scene", "prop") and not desc:
        return {"name": name, "kind": kind, "reason": "缺少可视化描述"}
    return None


def registry_completeness(assets: list[dict[str, Any]]) -> dict[str, Any]:
    incomplete = []
    for asset in assets:
        miss = _entry_incomplete(asset)
        if miss:
            incomplete.append(miss)
    counts = {"character": 0, "scene": 0, "prop": 0}
    for asset in assets:
        k = normalize_kind(asset.get("kind"))
        counts[k] = counts.get(k, 0) + 1
    return {
        "complete": len(incomplete) == 0 and counts["character"] > 0,
        "incomplete": incomplete,
        "counts": counts,
    }


def is_registry_complete(assets: list[dict[str, Any]]) -> bool:
    return bool(registry_completeness(assets)["complete"])


def _find_index(assets: list[dict[str, Any]], name: str, kind: str) -> int:
    needle = name.strip()
    for i, asset in enumerate(assets):
        if normalize_kind(asset.get("kind")) != kind:
            continue
        names = [asset.get("name"), *(asset.get("aliases") or [])]
        if needle in {str(n).strip() for n in names if n}:
            return i
    return -1


def apply_registry_delta(
    assets: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> tuple[int, int]:
    created = 0
    updated = 0
    for row in rows:
        kind = normalize_kind(row.get("kind"))
        name = (row.get("name") or "").strip()
        if not name:
            continue
        payload = {
            "kind": kind,
            "name": name,
            "aliases": row.get("aliases") or [],
            "refer_as": row.get("refer_as") or ("人" if kind == "character" else ""),
            "age_band": row.get("age_band") or "",
            "appearance": row.get("appearance") or {},
            "desc_zh": row.get("desc_zh") or row.get("notes") or "",
            "desc_en": row.get("desc_en") or "",
        }
        idx = _find_index(assets, name, kind)
        if idx < 0:
            assets.append(payload)
            created += 1
        else:
            assets[idx] = merge_registry_entry(assets[idx], payload)
            updated += 1
    return created, updated
