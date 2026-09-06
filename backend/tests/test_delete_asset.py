# -*- coding: utf-8 -*-
"""Delete whole asset (DB + files + shot refs)."""
from pathlib import Path

from fastapi.testclient import TestClient

from app import db as database
from app.db import Asset, Chapter, Project, Shot, reset_engine
from app.image_gen import resolve_image_output_dir, safe_asset_filename, kind_folder_name
from app.main import app
from app.services import _uid


def test_delete_asset_removes_files_and_shot_refs(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)

    db = database.SessionLocal()
    try:
        pid = _uid()
        aid = _uid()
        cid = _uid()
        sid = _uid()
        out = tmp_path / "out"
        p = Project(id=pid, title="t", style="国漫3D", source_text="x", image_output_dir=str(out))
        db.add(p)
        db.add(Chapter(id=cid, project_id=pid, index=0, title="一", text="x", status="storyboarded"))
        mirror = tmp_path / "projects" / pid / "assets" / aid
        mirror.mkdir(parents=True)
        (mirror / "full.png").write_bytes(b"full")
        (mirror / "half.png").write_bytes(b"half")
        rel_full = f"projects/{pid}/assets/{aid}/full.png"
        rel_half = f"projects/{pid}/assets/{aid}/half.png"
        a = Asset(
            id=aid,
            project_id=pid,
            kind="character",
            name="苏婆婆",
            full_path=rel_full,
            half_path=rel_half,
            desc_zh="白发",
        )
        db.add(a)
        kind_dir = out / kind_folder_name("character")
        kind_dir.mkdir(parents=True)
        out_full = kind_dir / f"{safe_asset_filename('苏婆婆')}_full.png"
        out_half = kind_dir / f"{safe_asset_filename('苏婆婆')}_half.png"
        out_full.write_bytes(b"full-out")
        out_half.write_bytes(b"half-out")
        db.add(
            Shot(
                id=sid,
                project_id=pid,
                chapter_id=cid,
                order_index=0,
                scene_asset_id="",
                lines_json=f'[{{"asset_id": "{aid}", "name": "苏婆婆", "position": "中"}}]',
                slots_json="[]",
                prop_asset_ids_json="[]",
            )
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    res = client.delete(f"/api/projects/{pid}/assets/{aid}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert all(a["id"] != aid for a in body["assets"])
    shot = next(s for s in body["shots"] if s["id"] == sid)
    assert all(not (ln.get("asset_id") or "") for ln in (shot.get("lines") or []))
    assert not (tmp_path / "projects" / pid / "assets" / aid).exists()
    assert not out_full.exists()
    assert not out_half.exists()
