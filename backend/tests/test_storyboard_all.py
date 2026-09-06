# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

from app import db as database
from app.db import Asset, Chapter, Project, Shot, reset_engine
from app.main import app
from app.services import _uid


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)
    monkeypatch.setattr("app.main._prepare_llm", lambda _db: None)

    async def fake_storyboard(db, project, chapter, overwrite=False, is_cancelled=None):
        from app.llm import ensure_not_cancelled

        await ensure_not_cancelled(is_cancelled)
        if not overwrite and db.query(Shot).filter(Shot.chapter_id == chapter.id).count():
            raise ValueError("本章已有分镜。若要重跑请勾选覆盖。")
        if overwrite:
            db.query(Shot).filter(Shot.chapter_id == chapter.id).delete()
        shot = Shot(
            id=_uid(),
            project_id=project.id,
            chapter_id=chapter.id,
            order_index=1,
            duration_s=6,
            prompt_zh="x",
            prompt_en="x",
            h3_prompt="x",
            lines_json="[]",
            prop_asset_ids_json="[]",
        )
        db.add(shot)
        chapter.status = "storyboarded"
        db.commit()
        return [{"id": shot.id}]

    monkeypatch.setattr("app.services.generate_storyboard", fake_storyboard)

    db = database.SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="国风", source_text="第一章\n甲\n\n第二章\n乙")
        db.add(p)
        c1 = Chapter(id=_uid(), project_id=pid, index=0, title="第一章", text="甲", status="assets_confirmed")
        c2 = Chapter(id=_uid(), project_id=pid, index=1, title="第二章", text="乙", status="assets_confirmed")
        db.add_all([c1, c2])
        db.add(
            Asset(
                id=_uid(),
                project_id=pid,
                kind="character",
                name="甲",
                confirmed=True,
                full_path="a/full.png",
                half_path="a/half.png",
            )
        )
        db.commit()
        return pid, c1.id, c2.id
    finally:
        db.close()


def test_storyboard_all_skips_existing_unless_overwrite(tmp_path, monkeypatch):
    pid, c1, c2 = _seed(tmp_path, monkeypatch)
    db = database.SessionLocal()
    try:
        db.add(
            Shot(
                id=_uid(),
                project_id=pid,
                chapter_id=c1,
                order_index=1,
                duration_s=6,
                prompt_zh="old",
                prompt_en="old",
                h3_prompt="old",
                lines_json="[]",
                prop_asset_ids_json="[]",
            )
        )
        ch = db.get(Chapter, c1)
        ch.status = "storyboarded"
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    out = client.post(f"/api/projects/{pid}/storyboard-all")
    assert out.status_code == 200, out.text
    body = out.json()
    assert c1 in body["skipped"]
    assert c2 in body["generated"]
    assert len(body["errors"]) == 0

    out2 = client.post(f"/api/projects/{pid}/storyboard-all?overwrite=true")
    assert out2.status_code == 200, out2.text
    body2 = out2.json()
    assert set(body2["generated"]) == {c1, c2}
    assert body2["skipped"] == []
