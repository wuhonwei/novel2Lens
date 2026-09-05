from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db import Asset, Chapter, Project, Proposal, Shot, project_dir
from app.config import settings
from app.domain.chapters import split_chapters
from app.domain.export import build_export_document, build_shots_markdown
from app.domain.prompts import compile_first_frame, compile_h3
from app.domain.registry import (
    apply_registry_delta,
    is_registry_complete,
    look_text,
    normalize_kind,
    registry_completeness,
    sanitize_aliases,
    sanitize_appearance,
    sanitize_character_fields,
    sanitize_look_text,
)
from app.domain.shot_refs import build_shot_references, scene_image_path
from app.domain.slots import (
    CAMERAS,
    FACINGS,
    MAX_NAMED_CHARACTERS,
    SlotSubject,
    max_named_characters,
    normalize_portrait_key,
    pack_qwen_slots,
)
from app.extract_prompts import (
    ASSET_SYSTEM,
    ASSET_USER,
    PRESCAN_AUDIT_SYSTEM,
    PRESCAN_AUDIT_USER,
    PRESCAN_PASS1_SYSTEM,
    PRESCAN_PASS1_USER,
    SHOT_SYSTEM,
    SHOT_USER,
)
from app.llm import chat_json

APPEARANCE_KEYS = ("face", "hair", "eyes", "skin", "body", "posture", "marks", "clothing", "condition", "time")
MAX_REGISTRY_AUDIT_PASSES = 5
NOVEL_SCAN_CHARS = 80000


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
    root = Path(settings.data_dir)
    for rel in fields:
        rel = (rel or "").strip()
        if not rel:
            continue
        path = Path(rel)
        if not path.is_absolute():
            path = root / rel
        try:
            if path.is_file():
                latest = max(latest, int(path.stat().st_mtime))
        except OSError:
            continue
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
        "references": references,
    }


def serialize_chapter(ch: Chapter) -> dict[str, Any]:
    return {
        "id": ch.id,
        "index": ch.index,
        "title": ch.title,
        "text": ch.text,
        "status": ch.status,
        "used_fallback_llm": ch.used_fallback_llm,
        "last_error": ch.last_error,
        "prescan_done": ch.prescan_done,
    }


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


async def full_registry_scan(db: Session, project: Project, *, replace: bool = False) -> dict[str, Any]:
    """Two-phase book registry: discover, then audit/supplement until complete.

    Assets are book-scoped (TXT-level), auto-confirmed — no per-chapter confirm.
    """
    novel = (project.source_text or "")[:NOVEL_SCAN_CHARS]
    if replace:
        db.query(Asset).filter(Asset.project_id == project.id).delete()
        db.flush()
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    passes: list[dict[str, Any]] = []
    used_fallback = False

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


async def prescan_project(db: Session, project: Project, replace: bool = False) -> dict[str, Any]:
    return await full_registry_scan(db, project, replace=replace)


async def _call_llm(project: Project, messages: list[dict[str, str]]) -> tuple[Any, bool]:
    return await chat_json(
        messages,
        primary_base=project.llm_base_url,
        primary_model=project.llm_model,
        fallback_base=project.fallback_base_url,
        fallback_model=project.fallback_model,
        allow_fallback=project.allow_fallback,
        thinking=project.thinking,
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


def _match_name(assets: list[Asset], name: str, kind: str | None = None) -> Asset | None:
    needle = (name or "").strip()
    pool = [a for a in assets if (kind is None or a.kind == kind)]
    for a in pool:
        if needle == a.name or needle in _load(a.aliases_json, []):
            return a
    return None


def _shot_unready(
    project: Project,
    image_reqs: list[tuple[Asset, str]],
) -> bool:
    if not (project.style or "").strip():
        return True
    for asset, image_key in image_reqs:
        key = image_key if image_key in ("scene", "prop") else normalize_portrait_key(image_key)
        if key == "half" and not asset.half_path:
            return True
        if key == "full" and not asset.full_path:
            return True
        if key == "scene" and not scene_image_path(asset):
            return True
        if key == "prop" and not asset.image_path:
            return True
    return False


def _asset_desc(asset: Asset) -> str:
    kind = normalize_kind(asset.kind)
    if kind == "character":
        return look_text(
            {
                "desc_zh": asset.desc_zh,
                "appearance": _load(asset.appearance_json, {}),
            }
        )
    return (asset.desc_zh or "").strip()


def _pick_portrait(raw_shot: dict[str, Any], person: dict[str, Any], named_count: int) -> str:
    explicit = person.get("portrait") or person.get("image_key")
    if explicit:
        return normalize_portrait_key(str(explicit))
    cam = str(raw_shot.get("camera") or "")
    blob = " ".join(
        str(x or "")
        for x in (
            person.get("action"),
            person.get("transient"),
            raw_shot.get("action"),
            raw_shot.get("camera_detail"),
        )
    )
    if named_count == 1 and (
        "推近" in cam or "特写" in blob or "近景" in blob or "面部" in blob or "脸" in blob
    ):
        return "half"
    return "full"


def _line_portrait_key(line: dict[str, Any], *, shot: Shot, line_count: int) -> str:
    explicit = line.get("image_key") or line.get("portrait")
    if explicit:
        return normalize_portrait_key(str(explicit))
    # Legacy half_lock packed full+half together; migrate to a single portrait.
    if bool(shot.half_lock) and line_count == 1:
        slots = _load(shot.slots_json, [])
        keys = [
            s.get("image_key")
            for s in slots
            if s.get("image_key") in ("half", "full") and (not line.get("asset_id") or s.get("asset_id") == line.get("asset_id"))
        ]
        if keys.count("full") and keys.count("half"):
            return "full"  # drop companion half-lock slot
        if keys == ["half"] or (keys and all(k == "half" for k in keys)):
            return "half"
    return "full"


LEGACY_DUAL_PORTRAIT_MARKERS = (
    "仅用于锁定面部",
    "外貌以半身像面部为准",
    "体态与服装以全身参考为准",
    "体态服装以全身图为准",
    "同一人物只使用其选定的一张人物参考图",
    "禁止同时套用半身与全身",
    "Each person uses only one portrait reference",
)


def shot_needs_portrait_repair(shot: Shot) -> bool:
    prompt = shot.prompt_zh or ""
    if any(m in prompt for m in LEGACY_DUAL_PORTRAIT_MARKERS):
        return True
    slots = _load(shot.slots_json, [])
    if len(slots) > 3:
        return True
    # Old packing put scene first; new priority puts characters first.
    if slots and slots[0].get("kind") == "scene" and any(s.get("kind") == "character" for s in slots):
        return True
    seen: set[str] = set()
    for slot in slots:
        if slot.get("image_key") not in ("half", "full"):
            continue
        aid = str(slot.get("asset_id") or "")
        if not aid:
            continue
        if aid in seen:
            return True
        seen.add(aid)
    return False


def compile_shot_prompts(project: Project, shot: Shot, assets: list[Asset]) -> None:
    by_id = {a.id: a for a in assets}
    scene = by_id.get(shot.scene_asset_id) if shot.scene_asset_id else None
    lines = _load(shot.lines_json, [])
    prop_ids = _load(getattr(shot, "prop_asset_ids_json", None) or "[]", [])
    prop_assets = [by_id[pid] for pid in prop_ids if pid in by_id]
    chars: list[SlotSubject] = []
    seen_char_ids: set[str] = set()
    for line in lines:
        asset = by_id.get(line.get("asset_id") or "")
        if not asset or asset.id in seen_char_ids:
            continue
        seen_char_ids.add(asset.id)
        image_key = _line_portrait_key(line, shot=shot, line_count=len(lines))
        line["image_key"] = image_key
        line["portrait"] = image_key
        chars.append(
            SlotSubject(
                asset_id=asset.id,
                kind="character",
                position=line.get("position") or "中",
                facing=line.get("facing") or "面向镜头",
                image_key=image_key,
                refer_as=asset.refer_as or "人",
                name=asset.name,
                desc_zh=_asset_desc(asset),
            )
        )
    shot.lines_json = _dump(lines)
    shot.character_count = len(chars)
    shot.half_lock = bool(len(chars) == 1 and chars and chars[0].image_key == "half")

    scene_subject = None
    if scene:
        scene_subject = SlotSubject(
            asset_id=scene.id,
            kind="scene",
            image_key="scene",
            name=scene.name,
            desc_zh=_asset_desc(scene),
        )
    prop_subjects = [
        SlotSubject(
            asset_id=p.id,
            kind="prop",
            image_key="prop",
            name=p.name,
            desc_zh=_asset_desc(p),
        )
        for p in prop_assets
    ]
    packed = pack_qwen_slots(
        characters=chars,
        scene=scene_subject,
        props=prop_subjects,
    )
    actions = {ln.get("position"): ln.get("action") or ln.get("transient") or "" for ln in lines}
    prompts = compile_first_frame(
        style=project.style,
        slots=packed.slots,
        character_count=shot.character_count,
        background=shot.background,
        actions=actions,
        text_fallbacks=packed.text_fallbacks,
    )
    h3_lines = []
    for ln in lines:
        asset = by_id.get(ln.get("asset_id") or "")
        h3_lines.append(
            {
                "position": ln.get("position") or "中",
                "refer_as": (asset.refer_as if asset else "") or "人",
                "facing": ln.get("facing") or "面向镜头",
                "action": ln.get("action") or "",
                "voice_direction": ln.get("voice_direction") or "",
                "dialogue": ln.get("dialogue") or "",
            }
        )
    shot.prompt_zh = prompts.zh
    shot.prompt_en = prompts.en
    shot.h3_prompt = compile_h3(
        camera=shot.camera,
        camera_detail=shot.camera_detail,
        character_count=shot.character_count,
        lines=h3_lines,
        narration=shot.narration,
    )
    slot_dump = []
    for p in packed.slots:
        asset = by_id.get(p.asset_id or "") if p.asset_id else None
        slot_dump.append(
            {
                "index": p.index,
                "kind": p.kind,
                "asset_id": p.asset_id,
                "asset_name": (asset.name if asset else "") or p.name,
                "position": p.position,
                "facing": p.facing,
                "image_key": p.image_key,
                "refer_as": p.refer_as,
            }
        )
    shot.slots_json = _dump(slot_dump)
    shot.text_fallbacks_json = _dump(
        [
            {
                "kind": fb.kind,
                "asset_id": fb.asset_id,
                "image_key": fb.image_key,
                "name": fb.name,
                "position": fb.position,
                "text": fb.text,
                "note": fb.note,
            }
            for fb in packed.text_fallbacks
        ]
    )
    image_reqs: list[tuple[Asset, str]] = []
    for p in packed.slots:
        asset = by_id.get(p.asset_id or "") if p.asset_id else None
        if asset:
            image_reqs.append((asset, p.image_key))
    shot.first_frame_unready = _shot_unready(project, image_reqs)



def repair_shot_prompts_if_needed(db: Session, project: Project, assets: list[Asset] | None = None) -> int:
    """Recompile shots that still use legacy dual half+full portrait prompts."""
    assets = assets if assets is not None else db.query(Asset).filter(Asset.project_id == project.id).all()
    fixed = 0
    for shot in db.query(Shot).filter(Shot.project_id == project.id):
        if shot_needs_portrait_repair(shot):
            compile_shot_prompts(project, shot, assets)
            fixed += 1
    if fixed:
        db.commit()
    return fixed



async def generate_storyboard(
    db: Session, project: Project, chapter: Chapter, overwrite: bool = False
) -> list[dict[str, Any]]:
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    book_ready = any(a.confirmed and normalize_kind(a.kind) == "character" for a in assets)
    if chapter.status not in ("assets_confirmed", "storyboarded") and not book_ready and not overwrite:
        raise ValueError("请先一键生成全书资产（人物/场景/物品）。")
    require_asset_images(assets)
    if overwrite:
        db.query(Shot).filter(Shot.chapter_id == chapter.id).delete()
    elif db.query(Shot).filter(Shot.chapter_id == chapter.id).count():
        raise ValueError("本章已有分镜。若要重跑请勾选覆盖。")

    chars = [a for a in assets if normalize_kind(a.kind) == "character"]
    scenes = [a for a in assets if normalize_kind(a.kind) == "scene"]
    props = [a for a in assets if normalize_kind(a.kind) == "prop"]
    user = SHOT_USER.format(
        style=project.style or "（未填画风）",
        characters=_registry(chars),
        scenes=_registry(scenes),
        props=_registry(props),
        title=chapter.title,
        chapter=chapter.text,
    )
    data, fallback = await _call_llm(
        project,
        [{"role": "system", "content": SHOT_SYSTEM}, {"role": "user", "content": user}],
    )
    raw_shots = data.get("shots") or []
    saved = []
    for i, raw in enumerate(raw_shots, start=1):
        named = raw.get("characters") or []
        scene_name = raw.get("scene_name")
        scene = _match_name(scenes, scene_name, "scene") if scene_name else None
        cap = max_named_characters()
        named = named[:cap]
        duration = float(raw.get("duration_s") or 6)
        duration = min(15.0, max(4.0, duration))
        camera = raw.get("camera") if raw.get("camera") in CAMERAS else "固定"
        lines = []
        for person in named:
            asset = _match_name(chars, person.get("name"), "character")
            if not asset:
                continue
            pos = person.get("position") if person.get("position") in ("左一", "中", "右一") else "中"
            facing = person.get("facing") if person.get("facing") in FACINGS else "面向镜头"
            image_key = _pick_portrait(raw, person, len(named))
            lines.append(
                {
                    "asset_id": asset.id,
                    "name": asset.name,
                    "position": pos,
                    "facing": facing,
                    "image_key": image_key,
                    "portrait": image_key,
                    "transient": person.get("transient") or "",
                    "action": person.get("action") or "",
                    "dialogue": person.get("dialogue") or "",
                    "voice_direction": person.get("voice_direction") or "",
                }
            )
        if len(lines) == 2:
            if lines[0]["position"] == lines[1]["position"]:
                lines[0]["position"], lines[1]["position"] = "左一", "右一"
            if lines[0]["facing"] == "面向镜头" and lines[1]["facing"] == "面向镜头":
                lines[0]["facing"], lines[1]["facing"] = "朝右", "朝左"
        if len(lines) == 1 and lines[0]["position"] not in ("左一", "中", "右一"):
            lines[0]["position"] = "中"
        half_lock = bool(len(lines) == 1 and lines and lines[0].get("image_key") == "half")
        prop_names = raw.get("prop_names") or raw.get("props") or []
        if isinstance(prop_names, str):
            prop_names = [prop_names]
        prop_ids: list[str] = []
        for pname in prop_names:
            if not isinstance(pname, str):
                continue
            prop = _match_name(props, pname, "prop")
            if prop and prop.id not in prop_ids:
                prop_ids.append(prop.id)
        shot = Shot(
            id=_uid(),
            project_id=project.id,
            chapter_id=chapter.id,
            order_index=i,
            duration_s=duration,
            scene_asset_id=scene.id if scene else "",
            prop_asset_ids_json=_dump(prop_ids),
            camera=camera,
            camera_detail=raw.get("camera_detail") or "",
            narration=raw.get("narration") or "",
            action=raw.get("action") or "",
            source_excerpt=raw.get("source_excerpt") or "",
            character_count=len(lines),
            background=raw.get("background") or "",
            lines_json=_dump(lines),
            half_lock=half_lock,
        )
        compile_shot_prompts(project, shot, assets)
        db.add(shot)
        saved.append(shot)
    chapter.status = "storyboarded"
    chapter.used_fallback_llm = fallback
    chapter.last_error = ""
    db.commit()
    return [serialize_shot(s, chapter.title, assets) for s in saved]


def update_shot(db: Session, project: Project, shot: Shot, patch: dict[str, Any]) -> dict[str, Any]:
    for key in ("duration_s", "camera", "camera_detail", "narration", "action", "source_excerpt", "background", "prompt_zh", "prompt_en", "h3_prompt"):
        if key in patch and patch[key] is not None:
            setattr(shot, key, patch[key])
    if "lines" in patch and patch["lines"] is not None:
        shot.lines_json = _dump(patch["lines"])
        shot.character_count = len(patch["lines"])
    if "scene_asset_id" in patch:
        shot.scene_asset_id = patch["scene_asset_id"] or ""
    if "prop_asset_ids" in patch and patch["prop_asset_ids"] is not None:
        shot.prop_asset_ids_json = _dump(patch["prop_asset_ids"])
    if "half_lock" in patch and patch["half_lock"] is not None:
        lines = _load(shot.lines_json, [])
        if len(lines) == 1:
            lines[0]["image_key"] = "half" if patch["half_lock"] else "full"
            lines[0]["portrait"] = lines[0]["image_key"]
            shot.lines_json = _dump(lines)
        shot.half_lock = bool(patch["half_lock"])
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    if patch.get("recompile", True):
        compile_shot_prompts(project, shot, assets)
    db.commit()
    chapter = db.query(Chapter).filter(Chapter.id == shot.chapter_id).one()
    return serialize_shot(shot, chapter.title, assets)


def save_upload(asset: Asset, field: str, filename: str, data: bytes) -> str:
    folder = project_dir(asset.project_id) / "assets" / asset.id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower() or ".png"
    kind = normalize_kind(asset.kind)
    asset.kind = kind
    # Non-characters only accept a single reference image.
    if kind != "character" and field in ("half", "full"):
        field = "image"
    dest = folder / f"{field}{suffix}"
    dest.write_bytes(data)
    stored = f"projects/{asset.project_id}/assets/{asset.id}/{dest.name}"
    if kind == "character":
        if field == "half":
            asset.half_path = stored
        elif field == "full":
            asset.full_path = stored
        elif field == "voice":
            asset.voice_path = stored
        else:
            asset.image_path = stored
    else:
        if field == "voice":
            asset.voice_path = stored
        else:
            asset.image_path = stored
            asset.half_path = ""
            asset.full_path = ""
    return stored


def refresh_shot_readiness(db: Session, project: Project) -> None:
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    for shot in db.query(Shot).filter(Shot.project_id == project.id):
        compile_shot_prompts(project, shot, assets)
    db.commit()


def export_project(db: Session, project: Project) -> tuple[dict[str, Any], str, Path]:
    chapters = db.query(Chapter).filter(Chapter.project_id == project.id).order_by(Chapter.index).all()
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    shots = db.query(Shot).filter(Shot.project_id == project.id).order_by(Shot.order_index).all()
    title_by_ch = {c.id: c.title for c in chapters}
    shot_docs = [serialize_shot(s, title_by_ch.get(s.chapter_id, ""), assets) for s in shots]
    doc = build_export_document(
        project={**serialize_project(project), "used_fallback_any": any(c.used_fallback_llm for c in chapters)},
        assets=[serialize_asset(a) for a in assets],
        chapters=[serialize_chapter(c) for c in chapters],
        shots=shot_docs,
    )
    md = build_shots_markdown(project.title, shot_docs)
    out_dir = project_dir(project.id) / "export" / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "novel2lens.json"
    md_path = out_dir / "shots.md"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(md, encoding="utf-8")
    return doc, md, json_path
