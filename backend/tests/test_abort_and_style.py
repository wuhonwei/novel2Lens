# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

from app import db as database
from app.db import Asset, ImageJob, Project, reset_engine
from app.image_jobs import cancel_project_jobs
from app.main import app
from app.services import _uid


def test_create_project_rejects_empty_style(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)

    client = TestClient(app)
    out = client.post("/api/projects", json={"title": "t", "text": "第一章\n字", "style": "  "})
    assert out.status_code == 400
    assert "画风" in out.json()["detail"]


def test_patch_project_rejects_blank_style(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)

    client = TestClient(app)
    created = client.post(
        "/api/projects",
        json={"title": "t", "text": "第一章\n字", "style": "半写实"},
    )
    assert created.status_code == 200, created.text
    pid = created.json()["project"]["id"]
    out = client.patch(f"/api/projects/{pid}", json={"style": ""})
    assert out.status_code == 400
    assert "画风" in out.json()["detail"]


def test_cancel_project_jobs_marks_active(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)

    db = database.SessionLocal()
    try:
        pid = _uid()
        db.add(Project(id=pid, title="t", style="s", source_text="x"))
        j1 = ImageJob(
            id=_uid(),
            project_id=pid,
            status="queued",
            kind="t2i",
            target_field="full",
            prompt="a",
            payload_json="{}",
        )
        j2 = ImageJob(
            id=_uid(),
            project_id=pid,
            status="running",
            kind="edit",
            target_field="half",
            prompt="b",
            payload_json="{}",
        )
        j3 = ImageJob(
            id=_uid(),
            project_id=pid,
            status="done",
            kind="t2i",
            target_field="image",
            prompt="c",
            payload_json="{}",
        )
        db.add_all([j1, j2, j3])
        db.commit()
        n = cancel_project_jobs(db, pid)
        assert n == 2
        db.refresh(j1)
        db.refresh(j2)
        db.refresh(j3)
        assert j1.status == "cancelled"
        assert j2.status == "cancelled"
        assert j3.status == "done"
    finally:
        db.close()

    client = TestClient(app)
    # seed via create then enqueue-like insert for API
    created = client.post("/api/projects", json={"title": "p2", "text": "第一章\n字", "style": "国风"})
    pid2 = created.json()["project"]["id"]
    db = database.SessionLocal()
    try:
        db.add(
            ImageJob(
                id=_uid(),
                project_id=pid2,
                status="queued",
                kind="t2i",
                target_field="full",
                prompt="x",
                payload_json="{}",
            )
        )
        db.commit()
    finally:
        db.close()
    out = client.post(f"/api/projects/{pid2}/image-jobs/cancel")
    assert out.status_code == 200, out.text
    assert out.json()["cancelled"] >= 1
