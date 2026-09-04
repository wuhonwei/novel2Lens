from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db import Asset, Chapter, Project, Proposal, Shot, project_dir
from app.domain.chapters import split_chapters
from app.domain.export import build_export_document, build_shots_markdown
from app.domain.prompts import compile_first_frame, compile_h3
from app.domain.slots import (
    CAMERAS,
    FACINGS,
    PackedSlot,
    SlotSubject,
    max_named_characters,
    pack_qwen_slots,
)
from app.extract_prompts import ASSET_SYSTEM, ASSET_USER, PRESCAN_SYSTEM, SHOT_SYSTEM, SHOT_USER
from app.llm import chat_json

APPEARANCE_KEYS = ("face", "hair", "eyes", "skin", "body", "posture", "marks", "clothing", "condition", "time")


def _uid() -> str:
    return str(uuid.uuid4())


def _load(raw: str, default: Any):
    try:
        return json.loads(raw or "") or default
    except json.JSONDecodeError:
        return default


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def serialize_asset(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "kind": asset.kind,
        "name": asset.name,
        "aliases": _load(asset.aliases_json, []),
        "refer_as": asset.refer_as,
        "age_band": asset.age_band,
        "appearance": _load(asset.appearance_json, {}),
        "desc_zh": asset.desc_zh,
        "desc_en": asset.desc_en,
        "parent_id": asset.parent_id,
        "variant_reason": asset.variant_reason,
        "confirmed": asset.confirmed,
        "half_path": asset.half_path,
        "full_path": asset.full_path,
        "image_path": asset.image_path,
        "voice_path": asset.voice_path,
        "created_chapter_id": asset.created_chapter_id,
        "portrait_ready": bool(asset.half_path and asset.full_path) if asset.kind == "character" else bool(asset.image_path),
    }


def serialize_shot(shot: Shot, chapter_title: str = "") -> dict[str, Any]:
    return {
        "id": shot.id,
        "chapter_id": shot.chapter_id,
        "chapter_title": chapter_title,
        "order_index": shot.order_index,
        "duration_s": shot.duration_s,
        "scene_asset_id": shot.scene_asset_id,
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
        "slots": _load(shot.slots_json, []),
        "lines": _load(shot.lines_json, []),
        "half_lock": shot.half_lock,
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
                "desc_zh": a.desc_zh,
                "appearance": _load(a.appearance_json, {}),
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


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


async def prescan_project(db: Session, project: Project) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": PRESCAN_SYSTEM},
        {"role": "user", "content": f"画风：{project.style}\n\n{project.source_text[:80000]}"},
    ]
    data, fallback = await _call_llm(project, messages)
    chapter = db.query(Chapter).filter(Chapter.project_id == project.id).order_by(Chapter.index).first()
    chapter_id = chapter.id if chapter else ""
    created = []
    for kind, key in (("character", "characters"), ("scene", "scenes"), ("prop", "props")):
        for row in data.get(key) or []:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            asset = Asset(
                id=_uid(),
                project_id=project.id,
                kind=kind,
                name=name,
                aliases_json=_dump(row.get("aliases") or []),
                refer_as=row.get("refer_as") or ("人" if kind == "character" else ""),
                age_band=row.get("age_band") or "",
                appearance_json=_dump({}),
                desc_zh=row.get("notes") or "",
                desc_en="",
                confirmed=False,
                created_chapter_id=chapter_id,
            )
            db.add(asset)
            created.append(serialize_asset(asset))
    for ch in db.query(Chapter).filter(Chapter.project_id == project.id):
        ch.prescan_done = True
        ch.used_fallback_llm = fallback
    db.commit()
    return {"used_fallback_llm": fallback, "assets": created}


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
        kind = row.get("kind") or "character"
        if action == "transient":
            continue
        if action == "create":
            asset = Asset(
                id=_uid(),
                project_id=project.id,
                kind=kind,
                name=(row.get("name") or "未命名").strip(),
                aliases_json=_dump(row.get("aliases") or []),
                refer_as=row.get("refer_as") or "",
                age_band=row.get("age_band") or "",
                appearance_json=_dump(row.get("appearance") or {}),
                desc_zh=row.get("desc_zh") or "",
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
        for slot in slots:
            if slot.get("asset_id") == drop_id:
                slot["asset_id"] = keep_id
        for line in lines:
            if line.get("asset_id") == drop_id:
                line["asset_id"] = keep_id
        shot.slots_json = _dump(slots)
        shot.lines_json = _dump(lines)
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


def _shot_unready(project: Project, scene: Asset | None, chars: list[Asset], half_lock: bool) -> bool:
    if not (project.style or "").strip():
        return True
    if scene and not scene.image_path:
        return True
    for ch in chars:
        if not (ch.half_path and ch.full_path):
            return True
    if half_lock and chars and not chars[0].half_path:
        return True
    return False


def compile_shot_prompts(project: Project, shot: Shot, assets: list[Asset]) -> None:
    by_id = {a.id: a for a in assets}
    scene = by_id.get(shot.scene_asset_id) if shot.scene_asset_id else None
    lines = _load(shot.lines_json, [])
    chars: list[SlotSubject] = []
    char_assets: list[Asset] = []
    for line in lines:
        asset = by_id.get(line.get("asset_id") or "")
        if not asset:
            continue
        char_assets.append(asset)
        chars.append(
            SlotSubject(
                asset_id=asset.id,
                position=line.get("position") or "中",
                facing=line.get("facing") or "面向镜头",
                image_key="full",
                refer_as=asset.refer_as or "人",
            )
        )
    has_scene = bool(scene)
    half_lock = bool(shot.half_lock and has_scene and len(chars) == 1)
    packed = pack_qwen_slots(has_scene=has_scene, characters=chars, half_lock=half_lock)
    if scene:
        packed[0].asset_id = scene.id
        packed[0].image_key = "scene"
    actions = {ln.get("position"): ln.get("action") or ln.get("transient") or "" for ln in lines}
    prompts = compile_first_frame(
        style=project.style,
        slots=packed,
        character_count=shot.character_count,
        background=shot.background,
        actions=actions,
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
    for p in packed:
        slot_dump.append(
            {
                "index": p.index,
                "kind": p.kind,
                "asset_id": p.asset_id,
                "position": p.position,
                "facing": p.facing,
                "image_key": p.image_key,
                "refer_as": p.refer_as,
            }
        )
    shot.slots_json = _dump(slot_dump)
    shot.first_frame_unready = _shot_unready(project, scene, char_assets, half_lock)


async def generate_storyboard(
    db: Session, project: Project, chapter: Chapter, overwrite: bool = False
) -> list[dict[str, Any]]:
    if chapter.status != "assets_confirmed" and not overwrite:
        raise ValueError("请先确认本章资产提案。")
    if overwrite:
        db.query(Shot).filter(Shot.chapter_id == chapter.id).delete()
    elif db.query(Shot).filter(Shot.chapter_id == chapter.id).count():
        raise ValueError("本章已有分镜。若要重跑请勾选覆盖。")

    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    chars = [a for a in assets if a.kind == "character"]
    scenes = [a for a in assets if a.kind == "scene"]
    props = [a for a in assets if a.kind == "prop"]
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
        cap = max_named_characters(has_scene=bool(scene))
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
            lines.append(
                {
                    "asset_id": asset.id,
                    "name": asset.name,
                    "position": pos,
                    "facing": facing,
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
        half_lock = bool(scene) and len(lines) == 1
        shot = Shot(
            id=_uid(),
            project_id=project.id,
            chapter_id=chapter.id,
            order_index=i,
            duration_s=duration,
            scene_asset_id=scene.id if scene else "",
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
    return [serialize_shot(s, chapter.title) for s in saved]


def update_shot(db: Session, project: Project, shot: Shot, patch: dict[str, Any]) -> dict[str, Any]:
    for key in ("duration_s", "camera", "camera_detail", "narration", "action", "source_excerpt", "background", "half_lock", "prompt_zh", "prompt_en", "h3_prompt"):
        if key in patch and patch[key] is not None:
            setattr(shot, key, patch[key])
    if "lines" in patch and patch["lines"] is not None:
        shot.lines_json = _dump(patch["lines"])
        shot.character_count = len(patch["lines"])
    if "scene_asset_id" in patch:
        shot.scene_asset_id = patch["scene_asset_id"] or ""
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    if patch.get("recompile", True):
        compile_shot_prompts(project, shot, assets)
    db.commit()
    chapter = db.query(Chapter).filter(Chapter.id == shot.chapter_id).one()
    return serialize_shot(shot, chapter.title)


def save_upload(asset: Asset, field: str, filename: str, data: bytes) -> str:
    folder = project_dir(asset.project_id) / "assets" / asset.id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower() or ".png"
    dest = folder / f"{field}{suffix}"
    dest.write_bytes(data)
    stored = f"projects/{asset.project_id}/assets/{asset.id}/{dest.name}"
    if field == "half":
        asset.half_path = stored
    elif field == "full":
        asset.full_path = stored
    elif field == "voice":
        asset.voice_path = stored
    else:
        asset.image_path = stored
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
    shot_docs = [serialize_shot(s, title_by_ch.get(s.chapter_id, "")) for s in shots]
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
