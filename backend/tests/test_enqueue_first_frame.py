"""Enqueue dedupe + multi-char ref packing."""
from __future__ import annotations

import json
from pathlib import Path

from app.db import Asset, Chapter, ImageJob, Project, Shot, reset_engine
from app.domain.registry import normalize_kind
from app.image_jobs import (
    _ordered_project_shots,
    _shot_ref_paths,
    enqueue_chapter_first_frames,
    enqueue_project_first_frames,
    enqueue_shot_first_frame,
)
from app.services import _uid
from app.storyboard_ops import ensure_or_create_scene_asset, ensure_shot_scene_asset


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _write_png(tmp_path: Path, rel: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(TINY_PNG)
    return rel


def test_multi_char_packs_four_character_refs(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 'pack.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="半写实", source_text="x")
        db.add(p)
        scene = Asset(
            id=_uid(),
            project_id=pid,
            kind="scene",
            name="渡口",
            desc_zh="江边渡口",
            confirmed=True,
            far_path=_write_png(tmp_path, f"assets/{pid}/scene_far.png"),
        )
        db.add(scene)
        chars = []
        for i, name in enumerate(["甲", "乙", "丙", "丁"]):
            a = Asset(
                id=_uid(),
                project_id=pid,
                kind="character",
                name=name,
                desc_zh="人",
                confirmed=True,
                full_path=_write_png(tmp_path, f"assets/{pid}/c{i}_full.png"),
            )
            chars.append(a)
            db.add(a)
        shot = Shot(
            id=_uid(),
            project_id=pid,
            chapter_id="ch",
            order_index=1,
            prompt_zh="四人站立",
            character_count=4,
            first_frame_unready=False,
            scene_asset_id=scene.id,
            lines_json=json.dumps(
                [{"asset_id": c.id, "position": "中", "facing": "面向镜头"} for c in chars]
            ),
            slots_json=json.dumps(
                [{"index": 1, "kind": "scene", "asset_id": scene.id, "image_key": "scene", "name": scene.name}]
                + [
                    {
                        "index": i + 2,
                        "kind": "character",
                        "asset_id": c.id,
                        "position": "中",
                        "facing": "面向镜头",
                        "image_key": "full",
                        "name": c.name,
                    }
                    for i, c in enumerate(chars)
                ]
            ),
        )
        db.add(shot)
        db.commit()
        paths, labels, err = _shot_ref_paths(p, shot, [scene, *chars])
        assert err == "", err
        assert len(paths) == 5, f"got {len(paths)} labels={labels}"
        assert any("场景" in lab or "scene" in lab.lower() for lab in labels)
    finally:
        db.close()


def test_chapter_enqueue_skips_existing_first_frame(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't_exist.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="半写实", source_text="x")
        db.add(p)
        a = Asset(
            id=_uid(),
            project_id=pid,
            kind="character",
            name="甲",
            confirmed=True,
            full_path=_write_png(tmp_path, f"assets/{pid}/c_full.png"),
        )
        db.add(a)
        scene = Asset(
            id=_uid(),
            project_id=pid,
            kind="scene",
            name="渡口",
            confirmed=True,
            far_path=_write_png(tmp_path, f"assets/{pid}/scene_far.png"),
        )
        db.add(scene)
        ch = Chapter(id=_uid(), project_id=pid, index=0, title="第一章", text="x", status="ready")
        db.add(ch)
        shot = Shot(
            id=_uid(),
            project_id=pid,
            chapter_id=ch.id,
            order_index=1,
            prompt_zh="一人",
            character_count=1,
            scene_asset_id=scene.id,
            first_frame_path=f"projects/{pid}/shots/s/first_frame.png",
            lines_json=json.dumps([{"asset_id": a.id, "position": "中", "facing": "面向镜头"}]),
            slots_json="[]",
        )
        db.add(shot)
        db.commit()
        monkeypatch.setattr(
            "app.image_jobs._shot_ref_paths",
            lambda *_a, **_k: ([str(tmp_path / a.full_path)], ["场景", "人物"], ""),
        )
        out = enqueue_chapter_first_frames(db, p, ch.id, overwrite=False)
        assert out["queued"] == 0
        assert out["skipped_existing"] == 1
        out2 = enqueue_chapter_first_frames(db, p, ch.id, overwrite=True)
        assert out2["queued"] == 1
    finally:
        db.close()
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't2.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="半写实", source_text="x")
        db.add(p)
        a = Asset(
            id=_uid(),
            project_id=pid,
            kind="character",
            name="甲",
            confirmed=True,
            full_path=_write_png(tmp_path, f"assets/{pid}/c_full.png"),
        )
        db.add(a)
        scene = Asset(
            id=_uid(),
            project_id=pid,
            kind="scene",
            name="渡口",
            confirmed=True,
            far_path=_write_png(tmp_path, f"assets/{pid}/scene_far.png"),
        )
        db.add(scene)
        ch = Chapter(id=_uid(), project_id=pid, index=0, title="第一章", text="x", status="ready")
        db.add(ch)
        shot = Shot(
            id=_uid(),
            project_id=pid,
            chapter_id=ch.id,
            order_index=1,
            prompt_zh="一人",
            character_count=1,
            scene_asset_id=scene.id,
            lines_json=json.dumps([{"asset_id": a.id, "position": "中", "facing": "面向镜头"}]),
            slots_json="[]",
        )
        db.add(shot)
        job = ImageJob(
            id=_uid(),
            project_id=pid,
            asset_id="",
            shot_id=shot.id,
            kind="edit",
            target_field="first_frame",
            prompt="x",
            status="queued",
            phase="",
            payload_json="{}",
        )
        db.add(job)
        db.commit()
        monkeypatch.setattr(
            "app.image_jobs._shot_ref_paths",
            lambda *_a, **_k: ([str(tmp_path / a.full_path)], ["场景", "人物"], ""),
        )
        out = enqueue_chapter_first_frames(db, p, ch.id)
        assert out["queued"] == 0
        assert out["skipped"] >= 1
    finally:
        db.close()


def test_shot_regen_cancels_prior_active(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't3.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="半写实", source_text="x")
        db.add(p)
        a = Asset(
            id=_uid(),
            project_id=pid,
            kind="character",
            name="甲",
            confirmed=True,
            full_path=_write_png(tmp_path, f"assets/{pid}/c_full.png"),
        )
        db.add(a)
        scene = Asset(
            id=_uid(),
            project_id=pid,
            kind="scene",
            name="渡口",
            confirmed=True,
            far_path=_write_png(tmp_path, f"assets/{pid}/scene_far.png"),
        )
        db.add(scene)
        ch = Chapter(id=_uid(), project_id=pid, index=0, title="第一章", text="x", status="ready")
        db.add(ch)
        shot = Shot(
            id=_uid(),
            project_id=pid,
            chapter_id=ch.id,
            order_index=1,
            prompt_zh="一人",
            character_count=1,
            scene_asset_id=scene.id,
            lines_json=json.dumps([{"asset_id": a.id, "position": "中", "facing": "面向镜头"}]),
            slots_json="[]",
        )
        db.add(shot)
        old = ImageJob(
            id=_uid(),
            project_id=pid,
            asset_id="",
            shot_id=shot.id,
            kind="edit",
            target_field="first_frame",
            prompt="old",
            status="queued",
            phase="",
            payload_json="{}",
        )
        db.add(old)
        db.commit()
        monkeypatch.setattr(
            "app.image_jobs._shot_ref_paths",
            lambda *_a, **_k: ([str(tmp_path / a.full_path)], ["场景", "人物"], ""),
        )
        monkeypatch.setattr("app.image_scores.clear_shot_first_frame_score", lambda *_a, **_k: None)
        new_job = enqueue_shot_first_frame(db, p, shot)
        db.refresh(old)
        assert old.status == "cancelled"
        assert new_job.status == "queued"
        assert new_job.id != old.id
        assert new_job.target_field == "first_frame"
    finally:
        db.close()


def test_project_first_frames_ordered_by_chapter_index(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 'order.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="半写实", source_text="x")
        db.add(p)
        scene = Asset(
            id=_uid(),
            project_id=pid,
            kind="scene",
            name="渡口",
            confirmed=True,
            far_path=_write_png(tmp_path, f"assets/{pid}/scene_far.png"),
        )
        db.add(scene)
        # UUID order would put ch_z before ch_a; chapter.index must win.
        ch2 = Chapter(id="ch_z_uuid", project_id=pid, index=1, title="第二章", text="x", status="ready")
        ch1 = Chapter(id="ch_a_uuid", project_id=pid, index=0, title="第一章", text="x", status="ready")
        db.add_all([ch2, ch1])
        for ch, orders in ((ch1, (2, 1)), (ch2, (1, 2))):
            for oi in orders:
                s = Shot(
                    id=_uid(),
                    project_id=pid,
                    chapter_id=ch.id,
                    order_index=oi,
                    prompt_zh=f"{ch.title}-{oi}",
                    character_count=0,
                    scene_asset_id=scene.id,
                    first_frame_unready=False,
                    lines_json="[]",
                    slots_json=json.dumps(
                        [
                            {
                                "index": 1,
                                "kind": "scene",
                                "asset_id": scene.id,
                                "image_key": "scene",
                                "name": scene.name,
                            }
                        ]
                    ),
                )
                db.add(s)
        db.commit()
        ordered = _ordered_project_shots(db, pid)
        assert [s.prompt_zh for s in ordered] == [
            "第一章-1",
            "第一章-2",
            "第二章-1",
            "第二章-2",
        ]
        monkeypatch.setattr(
            "app.image_jobs._shot_ref_paths",
            lambda *_a, **_k: ([str(tmp_path / scene.far_path)], ["参考场景图"], ""),
        )
        out = enqueue_project_first_frames(db, p, overwrite=True)
        assert out["queued"] == 4
        ff = [j for j in out["jobs"] if j["target_field"] == "first_frame"]
        assert [j["prompt"] for j in ff] == [
            "第一章-1",
            "第一章-2",
            "第二章-1",
            "第二章-2",
        ]
        assert [j["created_at"] for j in ff] == sorted(j["created_at"] for j in ff)
    finally:
        db.close()


def test_ensure_shot_scene_creates_temp_asset(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 'scene.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="半写实", source_text="x")
        db.add(p)
        char = Asset(
            id=_uid(),
            project_id=pid,
            kind="character",
            name="甲",
            confirmed=True,
            full_path=_write_png(tmp_path, f"assets/{pid}/c_full.png"),
        )
        db.add(char)
        shot = Shot(
            id=_uid(),
            project_id=pid,
            chapter_id="ch",
            order_index=3,
            prompt_zh="",
            background="废弃码头夜色",
            action="独自站立",
            character_count=1,
            scene_asset_id="",
            lines_json=json.dumps([{"asset_id": char.id, "position": "中", "facing": "面向镜头"}]),
            slots_json="[]",
        )
        db.add(shot)
        db.commit()
        assets = [char]
        scene = ensure_shot_scene_asset(db, p, shot, assets)
        db.commit()
        assert shot.scene_asset_id == scene.id
        assert normalize_kind(scene.kind) == "scene"
        assert "码头" in (scene.name or "") or "临时" in (scene.name or "") or "废弃" in (scene.name or "")
        core = ensure_or_create_scene_asset(
            db, p, scenes=[scene], scene_name=scene.name, background="x", order_index=1
        )
        assert core.id == scene.id
    finally:
        db.close()


def test_enqueue_queues_missing_scene_far_before_first_frame(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 'far.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="半写实", source_text="x")
        db.add(p)
        scene = Asset(
            id=_uid(),
            project_id=pid,
            kind="scene",
            name="夜码头",
            desc_zh="废弃码头夜色",
            confirmed=True,
            far_path="",  # missing plate
        )
        db.add(scene)
        char = Asset(
            id=_uid(),
            project_id=pid,
            kind="character",
            name="甲",
            confirmed=True,
            full_path=_write_png(tmp_path, f"assets/{pid}/c_full.png"),
        )
        db.add(char)
        ch = Chapter(id=_uid(), project_id=pid, index=0, title="第一章", text="x", status="ready")
        db.add(ch)
        shot = Shot(
            id=_uid(),
            project_id=pid,
            chapter_id=ch.id,
            order_index=1,
            prompt_zh="一人站码头",
            character_count=1,
            scene_asset_id=scene.id,
            first_frame_unready=False,
            lines_json=json.dumps([{"asset_id": char.id, "position": "中", "facing": "面向镜头"}]),
            slots_json=json.dumps(
                [
                    {
                        "index": 1,
                        "kind": "character",
                        "asset_id": char.id,
                        "image_key": "full",
                        "name": "甲",
                    }
                ]
            ),
            text_fallbacks_json=json.dumps(
                [
                    {
                        "kind": "scene",
                        "asset_id": scene.id,
                        "image_key": "scene",
                        "name": "夜码头",
                        "text": "废弃码头夜色",
                        "note": "文字描述补足",
                    }
                ]
            ),
        )
        db.add(shot)
        db.commit()
        out = enqueue_chapter_first_frames(db, p, ch.id, overwrite=True)
        assert out["queued"] == 1
        kinds = [(j["kind"], j["target_field"]) for j in out["jobs"]]
        assert ("t2i", "far") in kinds
        assert ("edit", "first_frame") in kinds
        far = next(j for j in out["jobs"] if j["target_field"] == "far")
        ff = next(j for j in out["jobs"] if j["target_field"] == "first_frame")
        assert far["created_at"] <= ff["created_at"]
        assert far["asset_id"] == scene.id
    finally:
        db.close()
