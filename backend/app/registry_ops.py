from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db import Asset, Chapter, Project, Proposal, Shot
from app.domain.chapters import split_chapters
from app.domain.registry import (
    apply_registry_delta,
    is_registry_complete,
    normalize_kind,
    registry_completeness,
    sanitize_aliases,
    sanitize_appearance,
    sanitize_character_fields,
    sanitize_look_text,
)
from app.extract_prompts import (
    ASSET_SYSTEM,
    ASSET_USER,
    PRESCAN_AUDIT_SYSTEM,
    PRESCAN_AUDIT_USER,
    PRESCAN_PASS1_SYSTEM,
    PRESCAN_PASS1_USER,
)
from app.llm import ensure_not_cancelled
from app.serialize import _dump, _load, _uid, serialize_asset

APPEARANCE_KEYS = ("face", "hair", "eyes", "skin", "body", "posture", "marks", "clothing", "condition", "time")
MAX_REGISTRY_AUDIT_PASSES = 5
NOVEL_SCAN_CHARS = 80000


def rebuild_chapters(db: Session, project: Project) -> None:
    db.query(Chapter).filter(Chapter.project_id == project.id).delete()
    for item in split_chapters(project.source_text):
        db.add(
            Chapter(
                id=_uid(),
                project_id=project.id,
                index=item.index,
                title=item.title,
                text=item.text,
                status="pending",
            )
        )


def _registry(assets: list[Asset]) -> str:
    rows = []
    for a in assets:
        rows.append(
            {
                "id": a.id,
                "kind": a.kind,
                "name": a.name,
                "aliases": _load(a.aliases_json, []),
                "refer_as": a.refer_as,
                "parent_id": a.parent_id,
                "background_zh": getattr(a, "background_zh", "") or "",
                "desc_zh": a.desc_zh,
                "appearance": _load(a.appearance_json, {}),
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


def _asset_dicts(assets: list[Asset]) -> list[dict[str, Any]]:
    return [
        {
            "id": a.id,
            "kind": normalize_kind(a.kind),
            "name": a.name,
            "aliases": _load(a.aliases_json, []),
            "refer_as": a.refer_as,
            "age_band": a.age_band,
            "appearance": _load(a.appearance_json, {}),
            "background_zh": getattr(a, "background_zh", "") or "",
            "desc_zh": a.desc_zh,
            "desc_en": a.desc_en,
        }
        for a in assets
    ]


def _find_db_asset(assets: list[Asset], name: str, kind: str) -> Asset | None:
    needle = name.strip()
    for asset in assets:
        if normalize_kind(asset.kind) != kind:
            continue
        names = [asset.name, *_load(asset.aliases_json, [])]
        if needle in {str(n).strip() for n in names if n}:
            return asset
    return None


def _apply_registry_rows_to_db(
    db: Session,
    project: Project,
    chapter_id: str,
    rows: list[dict[str, Any]],
    existing: list[Asset],
) -> tuple[int, int]:
    """Persist create/supplement rows; returns (created, updated)."""
    working = _asset_dicts(existing)
    created_n, updated_n = apply_registry_delta(working, rows)
    # Sync working back onto ORM objects / create new
    by_key: dict[tuple[str, str], Asset] = {}
    for asset in existing:
        by_key[(normalize_kind(asset.kind), asset.name)] = asset
        for alias in _load(asset.aliases_json, []):
            by_key[(normalize_kind(asset.kind), str(alias).strip())] = asset

    for row in working:
        kind = normalize_kind(row.get("kind"))
        name = (row.get("name") or "").strip()
        if not name:
            continue
        asset = _find_db_asset(existing, name, kind)
        if kind == "character":
            row = sanitize_character_fields(row)
            name = (row.get("name") or "").strip()
        aliases = sanitize_aliases(
            row.get("aliases") or [],
            name=name,
            refer_as=str(row.get("refer_as") or ""),
        )
        background_zh = (
            row.get("background_zh") or row.get("background") or row.get("identity") or ""
        ).strip()
        look_zh = (row.get("look_zh") or row.get("desc_zh") or "").strip()
        if kind == "character":
            if not look_zh:
                look_zh = (row.get("notes") or "").strip()
            # Prefer explicit look; if notes equals background, drop from look
            if look_zh and background_zh and look_zh == background_zh:
                look_zh = ""
            look_zh = sanitize_look_text(look_zh)
            appearance = sanitize_appearance(row.get("appearance") or {})
        else:
            look_zh = look_zh or (row.get("notes") or "").strip()
            appearance = row.get("appearance") or {}
        if asset is None:
            asset = Asset(
                id=_uid(),
                project_id=project.id,
                kind=kind,
                name=name,
                aliases_json=_dump(aliases),
                refer_as=row.get("refer_as") or ("人" if kind == "character" else ""),
                age_band=row.get("age_band") or "",
                appearance_json=_dump(appearance),
                background_zh=background_zh if kind == "character" else "",
                desc_zh=look_zh,
                desc_en=row.get("desc_en") or row.get("look_en") or "",
                confirmed=True,
                created_chapter_id=chapter_id,
            )
            db.add(asset)
            existing.append(asset)
        else:
            asset.kind = kind
            asset.aliases_json = _dump(aliases)
            if row.get("refer_as"):
                asset.refer_as = row["refer_as"]
            if row.get("age_band"):
                asset.age_band = row["age_band"]
            asset.appearance_json = _dump(appearance if kind == "character" else (row.get("appearance") or {}))
            if kind == "character" and background_zh:
                if not (asset.background_zh or "").strip():
                    asset.background_zh = background_zh
                elif background_zh not in asset.background_zh:
                    asset.background_zh = f"{asset.background_zh}；{background_zh}"
            if look_zh:
                prev = sanitize_look_text(asset.desc_zh) if kind == "character" else asset.desc_zh
                if not prev:
                    asset.desc_zh = look_zh
                elif look_zh not in prev:
                    asset.desc_zh = sanitize_look_text(f"{prev}；{look_zh}") if kind == "character" else f"{prev}；{look_zh}"
                else:
                    asset.desc_zh = prev
            elif kind == "character" and asset.desc_zh:
                asset.desc_zh = sanitize_look_text(asset.desc_zh)
            if row.get("desc_en") or row.get("look_en"):
                asset.desc_en = row.get("desc_en") or row.get("look_en") or asset.desc_en
            asset.confirmed = True
    db.flush()
    return created_n, updated_n


def _pass1_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    rows: list[dict[str, Any]] = []
    key_map = (
        ("characters", "character"),
        ("character", "character"),
        ("people", "character"),
        ("persons", "character"),
        ("人物", "character"),
        ("角色", "character"),
        ("人物形象", "character"),
        ("scenes", "scene"),
        ("scene", "scene"),
        ("locations", "scene"),
        ("场景", "scene"),
        ("地点", "scene"),
        ("核心场景", "scene"),
        ("props", "prop"),
        ("prop", "prop"),
        ("items", "prop"),
        ("objects", "prop"),
        ("物品", "prop"),
        ("道具", "prop"),
        ("核心物品", "prop"),
    )
    seen_keys: set[str] = set()
    for key, kind in key_map:
        if key in seen_keys:
            continue
        bucket = data.get(key)
        if not isinstance(bucket, list):
            continue
        seen_keys.add(key)
        for row in bucket:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item["kind"] = kind  # array membership wins over model-supplied kind
            rows.append(item)
    # Flat list fallbacks
    for key in ("assets", "registry", "entries", "登记表"):
        for row in data.get(key) or []:
            if isinstance(row, dict) and (row.get("name") or "").strip():
                item = dict(row)
                item["kind"] = normalize_kind(row.get("kind"))
                rows.append(item)
    return rows


def _audit_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("missing", "new_items", "supplements", "additions", "补充", "新增"):
        for row in data.get(key) or []:
            if isinstance(row, dict) and (row.get("name") or "").strip():
                item = dict(row)
                item["kind"] = normalize_kind(row.get("kind"))
                rows.append(item)
    # Also accept pass1-shaped audit payloads
    if not rows:
        rows = _pass1_rows(data)
    return rows


def detach_shot_asset_refs(db: Session, project_id: str) -> None:
    """Clear shot→asset id links so deleting/replacing assets cannot leave dangling refs."""
    for shot in db.query(Shot).filter(Shot.project_id == project_id):
        shot.scene_asset_id = ""
        slots = _load(shot.slots_json, [])
        lines = _load(shot.lines_json, [])
        for slot in slots:
            if isinstance(slot, dict):
                slot["asset_id"] = ""
        for line in lines:
            if isinstance(line, dict):
                line["asset_id"] = ""
        shot.slots_json = _dump(slots)
        shot.lines_json = _dump(lines)
        shot.prop_asset_ids_json = "[]"


async def full_registry_scan(
    db: Session, project: Project, *, replace: bool = False, is_cancelled=None
) -> dict[str, Any]:
    """Two-phase book registry: discover, then audit/supplement until complete.

    Assets are book-scoped (TXT-level), auto-confirmed — no per-chapter confirm.
    """
    novel = (project.source_text or "")[:NOVEL_SCAN_CHARS]
    if replace:
        detach_shot_asset_refs(db, project.id)
        db.query(Asset).filter(Asset.project_id == project.id).delete()
        db.flush()
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    passes: list[dict[str, Any]] = []
    used_fallback = False

    await ensure_not_cancelled(is_cancelled)
    # Pass 1 — discover
    data, fallback = await _call_llm(
        project,
        [
            {"role": "system", "content": PRESCAN_PASS1_SYSTEM},
            {
                "role": "user",
                "content": PRESCAN_PASS1_USER.format(style=project.style or "", novel=novel),
            },
        ],
        is_cancelled=is_cancelled,
    )
    used_fallback = used_fallback or fallback
    created, updated = _apply_registry_rows_to_db(db, project, "", _pass1_rows(data), assets)
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    passes.append(
        {
            "pass": 1,
            "phase": "discover",
            "created": created,
            "updated": updated,
            "completeness": registry_completeness(_asset_dicts(assets)),
        }
    )

    # Pass 2+ — audit / supplement loop
    for audit_i in range(1, MAX_REGISTRY_AUDIT_PASSES + 1):
        await ensure_not_cancelled(is_cancelled)
        assets = db.query(Asset).filter(Asset.project_id == project.id).all()
        if is_registry_complete(_asset_dicts(assets)) and audit_i > 1:
            break
        data, fallback = await _call_llm(
            project,
            [
                {"role": "system", "content": PRESCAN_AUDIT_SYSTEM},
                {
                    "role": "user",
                    "content": PRESCAN_AUDIT_USER.format(
                        style=project.style or "",
                        pass_no=audit_i + 1,
                        registry=_registry(assets),
                        novel=novel,
                    ),
                },
            ],
            is_cancelled=is_cancelled,
        )
        used_fallback = used_fallback or fallback
        rows = _audit_rows(data)
        created, updated = _apply_registry_rows_to_db(db, project, "", rows, assets)
        assets = db.query(Asset).filter(Asset.project_id == project.id).all()
        complete_flag = bool(isinstance(data, dict) and data.get("complete")) and not rows
        completeness = registry_completeness(_asset_dicts(assets))
        passes.append(
            {
                "pass": audit_i + 1,
                "phase": "audit",
                "created": created,
                "updated": updated,
                "llm_complete": complete_flag,
                "completeness": completeness,
            }
        )
        if completeness["complete"] or (complete_flag and created == 0 and updated == 0):
            break
        if created == 0 and updated == 0 and not rows:
            break

    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    # Normalize kinds + scrub bad aliases + auto-confirm book registry
    for asset in assets:
        asset.kind = normalize_kind(asset.kind)
        if asset.kind == "character":
            cleaned = sanitize_character_fields(
                {
                    "name": asset.name,
                    "aliases": _load(asset.aliases_json, []),
                    "refer_as": asset.refer_as,
                    "desc_zh": asset.desc_zh,
                    "appearance": _load(asset.appearance_json, {}),
                }
            )
            asset.aliases_json = _dump(cleaned["aliases"])
            if cleaned.get("refer_as"):
                asset.refer_as = cleaned["refer_as"]
            asset.desc_zh = sanitize_look_text(cleaned.get("desc_zh") or asset.desc_zh)
            asset.appearance_json = _dump(sanitize_appearance(cleaned.get("appearance") or {}))
        else:
            asset.aliases_json = _dump(
                sanitize_aliases(_load(asset.aliases_json, []), name=asset.name)
            )
        asset.confirmed = True
        asset.created_chapter_id = asset.created_chapter_id or ""

    final = registry_completeness(_asset_dicts(assets))
    scan_meta = {
        "passes": passes,
        "complete": final["complete"],
        "counts": final["counts"],
        "incomplete": final["incomplete"],
        "used_fallback_llm": used_fallback,
    }
    project.registry_scan_json = _dump(scan_meta)
    for ch in db.query(Chapter).filter(Chapter.project_id == project.id):
        ch.prescan_done = True
        ch.used_fallback_llm = used_fallback
        # Book assets ready → chapters can storyboard without per-chapter confirm
        if ch.status in ("pending", "proposals"):
            ch.status = "assets_confirmed"
    db.commit()
    return {
        "used_fallback_llm": used_fallback,
        "passes": passes,
        "complete": final["complete"],
        "counts": final["counts"],
        "assets": [serialize_asset(a) for a in assets],
    }


async def prescan_project(
    db: Session, project: Project, replace: bool = False, is_cancelled=None
) -> dict[str, Any]:
    return await full_registry_scan(db, project, replace=replace, is_cancelled=is_cancelled)


async def _call_llm(
    project: Project, messages: list[dict[str, str]], *, is_cancelled=None
) -> tuple[Any, bool]:
    # Resolve via services facade so tests can monkeypatch app.services.chat_json.
    from app import services as _services

    return await _services.chat_json(
        messages,
        primary_base=project.llm_base_url,
        primary_model=project.llm_model,
        fallback_base=project.fallback_base_url,
        fallback_model=project.fallback_model,
        allow_fallback=project.allow_fallback,
        thinking=project.thinking,
        is_cancelled=is_cancelled,
    )


def _normalize_proposals(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    if data.get("proposals"):
        return [x for x in data["proposals"] if isinstance(x, dict)]
    if data.get("items"):
        return [x for x in data["items"] if isinstance(x, dict)]
    out: list[dict[str, Any]] = []
    mapping = (("characters", "character"), ("scenes", "scene"), ("props", "prop"), ("locations", "scene"))
    for key, kind in mapping:
        for row in data.get(key) or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item.setdefault("kind", kind)
            item.setdefault("action", "create")
            out.append(item)
    return out


async def extract_assets(db: Session, project: Project, chapter: Chapter, overwrite: bool = False) -> dict[str, Any]:
    if chapter.status not in ("pending", "proposals") and not overwrite:
        raise ValueError("本章已确认资产。若要重跑请勾选覆盖。")
    if overwrite:
        db.query(Proposal).filter(Proposal.chapter_id == chapter.id, Proposal.status == "pending").delete()
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    user = ASSET_USER.format(
        style=project.style or "（未填画风）",
        registry=_registry(assets),
        title=chapter.title,
        chapter=chapter.text,
    )
    data, fallback = await _call_llm(
        project,
        [{"role": "system", "content": ASSET_SYSTEM}, {"role": "user", "content": user}],
    )
    proposals = _normalize_proposals(data)
    if not proposals:
        retry_user = user + "\n\n上一轮没有 proposals。必须输出非空 proposals 数组，至少包含本章出场的具名人物。"
        data, fallback2 = await _call_llm(
            project,
            [{"role": "system", "content": ASSET_SYSTEM}, {"role": "user", "content": retry_user}],
        )
        fallback = fallback or fallback2
        proposals = _normalize_proposals(data)
    stored = []
    for row in proposals:
        prop = Proposal(
            id=_uid(),
            project_id=project.id,
            chapter_id=chapter.id,
            payload_json=_dump(row),
            status="pending",
        )
        db.add(prop)
        stored.append({"id": prop.id, **row})
    chapter.status = "proposals"
    chapter.used_fallback_llm = fallback
    chapter.last_error = ""
    db.commit()
    return {"used_fallback_llm": fallback, "proposals": stored}


def _find_asset(assets: list[Asset], name: str | None, asset_id: str | None) -> Asset | None:
    if asset_id:
        for a in assets:
            if a.id == asset_id:
                return a
    needle = (name or "").strip()
    if not needle:
        return None
    for a in assets:
        aliases = [a.name, *(_load(a.aliases_json, []))]
        if needle in aliases:
            return a
    return None


def _merge_appearance(old: dict, incoming: dict) -> dict:
    merged = dict(old or {})
    for key, value in (incoming or {}).items():
        if value in (None, ""):
            continue
        if key not in merged or not merged[key]:
            merged[key] = value
        elif key == "clothing" and value != merged.get(key):
            continue
        else:
            merged[key] = value if not merged[key] else merged[key]
            if not old.get(key):
                merged[key] = value
    return merged


def confirm_proposals(
    db: Session,
    project: Project,
    chapter: Chapter,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    by_id = {p.id: p for p in db.query(Proposal).filter(Proposal.chapter_id == chapter.id).all()}
    order = {"merge": 0, "create": 1, "supplement": 2, "clone_variant": 3, "transient": 4}
    items = sorted(items, key=lambda r: order.get(r.get("action") or "", 9))
    for row in items:
        pid = row.get("id")
        if pid and pid in by_id:
            by_id[pid].status = "applied" if row.get("accept", True) else "discarded"
            by_id[pid].payload_json = _dump({**_load(by_id[pid].payload_json, {}), **row})
        if not row.get("accept", True):
            continue
        action = row.get("action")
        kind = normalize_kind(row.get("kind") or "character")
        if action == "transient":
            continue
        if action == "create":
            existing = _find_asset(assets, row.get("name"), row.get("match_asset_id"))
            if existing and normalize_kind(existing.kind) == kind:
                # Book scan already registered — treat as supplement + confirm.
                aliases = _load(existing.aliases_json, [])
                for a in row.get("aliases") or []:
                    if a and a not in aliases and a != existing.name:
                        aliases.append(a)
                existing.aliases_json = _dump(aliases)
                if row.get("refer_as"):
                    existing.refer_as = row["refer_as"]
                if row.get("age_band"):
                    existing.age_band = row["age_band"]
                existing.appearance_json = _dump(
                    _merge_appearance(_load(existing.appearance_json, {}), row.get("appearance") or {})
                )
                bg = (row.get("background_zh") or row.get("background") or "").strip()
                if bg:
                    if not (getattr(existing, "background_zh", "") or "").strip():
                        existing.background_zh = bg
                    elif bg not in existing.background_zh:
                        existing.background_zh = f"{existing.background_zh}；{bg}"
                look = (row.get("look_zh") or row.get("desc_zh") or "").strip()
                if look:
                    if not existing.desc_zh:
                        existing.desc_zh = look
                    elif look not in existing.desc_zh:
                        existing.desc_zh = f"{existing.desc_zh}；{look}"
                if row.get("desc_en") and not existing.desc_en:
                    existing.desc_en = row["desc_en"]
                existing.confirmed = True
                existing.kind = kind
            else:
                look = (row.get("look_zh") or row.get("desc_zh") or "").strip()
                asset = Asset(
                    id=_uid(),
                    project_id=project.id,
                    kind=kind,
                    name=(row.get("name") or "未命名").strip(),
                    aliases_json=_dump(row.get("aliases") or []),
                    refer_as=row.get("refer_as") or "",
                    age_band=row.get("age_band") or "",
                    appearance_json=_dump(row.get("appearance") or {}),
                    background_zh=(row.get("background_zh") or row.get("background") or "") if kind == "character" else "",
                    desc_zh=look,
                    desc_en=row.get("desc_en") or "",
                    confirmed=True,
                    created_chapter_id=chapter.id,
                )
                db.add(asset)
                assets.append(asset)
        elif action == "merge":
            target = _find_asset(assets, row.get("name"), row.get("match_asset_id"))
            if not target:
                continue
            aliases = _load(target.aliases_json, [])
            extra = row.get("aliases") or []
            if row.get("name") and row["name"] not in aliases and row["name"] != target.name:
                aliases.append(row["name"])
            for a in extra:
                if a and a not in aliases:
                    aliases.append(a)
            target.aliases_json = _dump(aliases)
            target.confirmed = True
        elif action == "supplement":
            target = _find_asset(assets, row.get("name"), row.get("match_asset_id"))
            if not target:
                continue
            appearance = _merge_appearance(_load(target.appearance_json, {}), row.get("appearance") or {})
            target.appearance_json = _dump(appearance)
            if row.get("desc_zh"):
                target.desc_zh = (target.desc_zh + "\n" + row["desc_zh"]).strip() if target.desc_zh else row["desc_zh"]
            if row.get("desc_en") and not target.desc_en:
                target.desc_en = row["desc_en"]
            if row.get("refer_as") and not target.refer_as:
                target.refer_as = row["refer_as"]
            target.confirmed = True
        elif action == "clone_variant":
            source = _find_asset(assets, row.get("name"), row.get("match_asset_id"))
            if not source:
                continue
            appearance = dict(_load(source.appearance_json, {}))
            appearance.update({k: v for k, v in (row.get("appearance") or {}).items() if v})
            clone = Asset(
                id=_uid(),
                project_id=project.id,
                kind=source.kind,
                name=source.name,
                aliases_json=source.aliases_json,
                refer_as=row.get("refer_as") or source.refer_as,
                age_band=row.get("age_band") or source.age_band,
                appearance_json=_dump(appearance),
                desc_zh=row.get("desc_zh") or source.desc_zh,
                desc_en=row.get("desc_en") or source.desc_en,
                parent_id=source.id,
                variant_reason=row.get("variant_reason") or "other",
                confirmed=True,
                created_chapter_id=chapter.id,
            )
            db.add(clone)
            assets.append(clone)
    chapter.status = "assets_confirmed"
    db.commit()
    return [serialize_asset(a) for a in db.query(Asset).filter(Asset.project_id == project.id).all()]


def merge_assets(db: Session, project_id: str, keep_id: str, drop_id: str) -> None:
    keep = db.query(Asset).filter(Asset.id == keep_id, Asset.project_id == project_id).one()
    drop = db.query(Asset).filter(Asset.id == drop_id, Asset.project_id == project_id).one()
    aliases = _load(keep.aliases_json, [])
    if drop.name not in aliases and drop.name != keep.name:
        aliases.append(drop.name)
    for a in _load(drop.aliases_json, []):
        if a not in aliases:
            aliases.append(a)
    keep.aliases_json = _dump(aliases)
    for shot in db.query(Shot).filter(Shot.project_id == project_id):
        if shot.scene_asset_id == drop_id:
            shot.scene_asset_id = keep_id
        slots = _load(shot.slots_json, [])
        lines = _load(shot.lines_json, [])
        prop_ids = _load(getattr(shot, "prop_asset_ids_json", None) or "[]", [])
        for slot in slots:
            if slot.get("asset_id") == drop_id:
                slot["asset_id"] = keep_id
        for line in lines:
            if line.get("asset_id") == drop_id:
                line["asset_id"] = keep_id
        prop_ids = [keep_id if pid == drop_id else pid for pid in prop_ids]
        deduped: list[str] = []
        for pid in prop_ids:
            if pid and pid not in deduped:
                deduped.append(pid)
        shot.slots_json = _dump(slots)
        shot.lines_json = _dump(lines)
        shot.prop_asset_ids_json = _dump(deduped)
    db.query(Asset).filter(Asset.parent_id == drop_id).update({"parent_id": keep_id})
    db.delete(drop)
    db.commit()
