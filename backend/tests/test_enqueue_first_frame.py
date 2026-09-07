"""Enqueue dedupe + multi-char ref packing."""
from __future__ import annotations

import json
from pathlib import Path

from app.db import Asset, Chapter, ImageJob, Project, Shot, reset_engine
from app.image_jobs import (
    _shot_ref_paths,
    enqueue_chapter_first_frames,
    enqueue_shot_first_frame,
)
from app.services import _uid


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_multi_char_packs_four_character_refs(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 'pack.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="半写实", source_text="x")
        db.add(p)
        chars = []
        for i, name in enumerate(["甲", "乙", "丙", "丁"]):
            a = Asset(
                id=_uid(),
                project_id=pid,
                kind="character",
                name=name,
                desc_zh="人",
                confirmed=True,
                full_path=f"assets/{pid}/c{i}_full.png",
            )
            (tmp_path / a.full_path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / a.full_path).write_bytes(TINY_PNG)
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
            lines_json=json.dumps(
                [{"asset_id": c.id, "position": "中", "facing": "面向镜头"} for c in chars]
            ),
            slots_json=json.dumps(
                [
                    {
                        "index": i + 1,
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
        paths, labels, err = _shot_ref_paths(p, shot, chars)
        assert err == "", err
        assert len(paths) == 4, f"got {len(paths)} labels={labels}"
    finally:
        db.close()


def test_chapter_enqueue_skips_active_shot(tmp_path, monkeypatch):
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
            full_path=f"assets/{pid}/c_full.png",
        )
        (tmp_path / a.full_path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / a.full_path).write_bytes(TINY_PNG)
        db.add(a)
        ch = Chapter(id=_uid(), project_id=pid, index=0, title="第一章", text="x", status="ready")
        db.add(ch)
        shot = Shot(
            id=_uid(),
            project_id=pid,
            chapter_id=ch.id,
            order_index=1,
            prompt_zh="一人",
            character_count=1,
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
            lambda *_a, **_k: ([str(tmp_path / a.full_path)], ["人物"], ""),
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
            full_path=f"assets/{pid}/c_full.png",
        )
        (tmp_path / a.full_path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / a.full_path).write_bytes(TINY_PNG)
        db.add(a)
        ch = Chapter(id=_uid(), project_id=pid, index=0, title="第一章", text="x", status="ready")
        db.add(ch)
        shot = Shot(
            id=_uid(),
            project_id=pid,
            chapter_id=ch.id,
            order_index=1,
            prompt_zh="一人",
            character_count=1,
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
            lambda *_a, **_k: ([str(tmp_path / a.full_path)], ["人物"], ""),
        )
        monkeypatch.setattr("app.image_scores.clear_shot_first_frame_score", lambda *_a, **_k: None)
        new_job = enqueue_shot_first_frame(db, p, shot)
        db.refresh(old)
        assert old.status == "cancelled"
        assert new_job.status == "queued"
        assert new_job.id != old.id
    finally:
        db.close()
