from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db import Asset, Chapter, Project, Shot, project_dir
from app.domain.export import build_export_document, build_shots_markdown
from app.domain.prompts import compile_first_frame, compile_h3
from app.domain.registry import look_text, normalize_kind
from app.domain.shot_refs import scene_image_path
from app.domain.slots import (
    CAMERAS,
    FACINGS,
    SlotSubject,
    max_named_characters,
    normalize_portrait_key,
    pack_qwen_slots,
)
from app.extract_prompts import SHOT_SYSTEM, SHOT_USER
from app.llm import OperationCancelled, ensure_not_cancelled
from app.registry_ops import _call_llm, _registry
from app.serialize import (
    _dump,
    _load,
    _uid,
    require_asset_images,
    serialize_asset,
    serialize_chapter,
    serialize_project,
    serialize_shot,
)


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
    db: Session, project: Project, chapter: Chapter, overwrite: bool = False, is_cancelled=None
) -> list[dict[str, Any]]:
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    repair_shot_prompts_if_needed(db, project, assets)
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
    await ensure_not_cancelled(is_cancelled)
    data, fallback = await _call_llm(
        project,
        [{"role": "system", "content": SHOT_SYSTEM}, {"role": "user", "content": user}],
        is_cancelled=is_cancelled,
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


async def generate_all_storyboards(
    db: Session,
    project: Project,
    *,
    overwrite: bool = False,
    is_cancelled=None,
) -> dict[str, Any]:
    """Generate storyboards for every chapter; skip chapters that already have shots unless overwrite."""
    chapters = (
        db.query(Chapter)
        .filter(Chapter.project_id == project.id)
        .order_by(Chapter.index.asc())
        .all()
    )
    generated: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    for chapter in chapters:
        try:
            await ensure_not_cancelled(is_cancelled)
        except OperationCancelled:
            return {
                "ok": False,
                "cancelled": True,
                "generated": generated,
                "skipped": skipped,
                "errors": errors + ["已终止"],
            }
        has_shots = db.query(Shot).filter(Shot.chapter_id == chapter.id).count() > 0
        if has_shots and not overwrite:
            skipped.append(chapter.id)
            continue
        try:
            # Resolve via services facade so tests can monkeypatch app.services.generate_storyboard.
            from app import services as _services

            await _services.generate_storyboard(
                db,
                project,
                chapter,
                overwrite=overwrite,
                is_cancelled=is_cancelled,
            )
            generated.append(chapter.id)
        except OperationCancelled:
            return {
                "ok": False,
                "cancelled": True,
                "generated": generated,
                "skipped": skipped,
                "errors": errors + ["已终止"],
            }
        except ValueError as exc:
            errors.append(f"{chapter.title}: {exc}")
            chapter.last_error = str(exc)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{chapter.title}: {exc}")
            chapter.last_error = str(exc)
            db.commit()
    return {
        "ok": len(errors) == 0,
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
        "cancelled": False,
    }


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
    # Characters: half/full/voice/image. Scenes: far/near (also accept legacy image). Props: image.
    if kind == "character" and field in ("far", "near"):
        field = "image"
    if kind == "scene" and field in ("half", "full"):
        field = "far" if field == "full" else "near"
    if kind == "prop" and field in ("half", "full", "far", "near"):
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
    elif kind == "scene":
        if field == "near":
            asset.near_path = stored
        elif field == "voice":
            asset.voice_path = stored
        else:
            # far (default) + legacy image
            asset.far_path = stored
            if field == "image" or not asset.image_path:
                asset.image_path = stored
    else:
        if field == "voice":
            asset.voice_path = stored
        else:
            asset.image_path = stored
            asset.half_path = ""
            asset.full_path = ""
    return stored


def _shot_mentions_asset(shot: Shot, asset_id: str) -> bool:
    if not asset_id:
        return True
    if (shot.scene_asset_id or "") == asset_id:
        return True
    prop_ids = _load(getattr(shot, "prop_asset_ids_json", None) or "[]", [])
    if asset_id in prop_ids:
        return True
    for line in _load(shot.lines_json, []):
        if str(line.get("asset_id") or "") == asset_id:
            return True
    for slot in _load(shot.slots_json, []):
        if str(slot.get("asset_id") or "") == asset_id:
            return True
    return False


def refresh_shot_readiness(
    db: Session,
    project: Project,
    *,
    commit: bool = True,
    asset_id: str | None = None,
) -> None:
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    for shot in db.query(Shot).filter(Shot.project_id == project.id):
        if asset_id and not _shot_mentions_asset(shot, asset_id):
            continue
        compile_shot_prompts(project, shot, assets)
    if commit:
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
