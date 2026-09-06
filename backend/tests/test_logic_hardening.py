# -*- coding: utf-8 -*-
"""Regression tests for obvious pipeline logic holes."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db as database
from app.db import Asset, Chapter, ImageJob, Project, Shot, reset_engine
from app.main import app, llm_supervisor
from app.services import _uid, save_upload


def test_prepare_llm_calls_ensure_llm(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("app.main._reject_if_image_busy", lambda _db: None)
    monkeypatch.setattr(
        "app.main.comfy_supervisor.release_for_llm",
        lambda: calls.append("release"),
    )
    monkeypatch.setattr("app.main.llm_supervisor.ensure_llm", lambda: calls.append("ensure"))
    from app.db import Project
    from app.main import _prepare_llm

    project = Project(id="p", title="t", style="x", source_text="x", llm_base_url="http://127.0.0.1:8080/v1")
    _prepare_llm(object(), project)
    assert calls == ["release", "ensure"]


def test_prepare_llm_skips_ensure_for_ollama_primary(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("app.main._reject_if_image_busy", lambda _db: None)
    monkeypatch.setattr(
        "app.main.comfy_supervisor.release_for_llm",
        lambda: calls.append("release"),
    )
    monkeypatch.setattr("app.main.llm_supervisor.ensure_llm", lambda: calls.append("ensure"))
    from app.db import Project
    from app.main import _prepare_llm

    project = Project(id="p", title="t", style="x", source_text="x", llm_base_url="http://127.0.0.1:11434/v1")
    _prepare_llm(object(), project)
    assert calls == ["release"]


def test_score_images_rejects_when_image_busy(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)
    monkeypatch.setattr("app.ollama_vram.unload_all_ollama", lambda: [])

    db = database.SessionLocal()
    try:
        pid = _uid()
        db.add(Project(id=pid, title="t", style="国漫3D", source_text="x"))
        db.commit()
    finally:
        db.close()

    llm_supervisor.set_image_busy(True)
    try:
        client = TestClient(app)
        out = client.post(f"/api/projects/{pid}/score-images", json={"scope": "assets"})
        assert out.status_code == 409, out.text
    finally:
        llm_supervisor.set_image_busy(False)


def test_save_upload_scene_far_near(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    db = database.SessionLocal()
    try:
        pid = _uid()
        aid = _uid()
        db.add(Project(id=pid, title="t", style="国漫3D", source_text="x"))
        a = Asset(id=aid, project_id=pid, kind="scene", name="渡口")
        db.add(a)
        db.commit()
        png = b"\x89PNG\r\n\x1a\n"
        save_upload(a, "far", "far.png", png)
        save_upload(a, "near", "near.png", png)
        db.commit()
        db.refresh(a)
        assert a.far_path.endswith("/far.png")
        assert a.near_path.endswith("/near.png")
    finally:
        db.close()


def test_upload_api_accepts_scene_far_near(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)

    db = database.SessionLocal()
    try:
        pid = _uid()
        aid = _uid()
        db.add(Project(id=pid, title="t", style="国漫3D", source_text="x"))
        db.add(Asset(id=aid, project_id=pid, kind="scene", name="渡口"))
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    out = client.post(
        f"/api/projects/{pid}/assets/{aid}/upload",
        data={"field": "far"},
        files={"file": ("far.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert body.get("far_path"), body


def test_detach_shot_asset_refs_clears_ids(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    db = database.SessionLocal()
    try:
        pid = _uid()
        old_id = _uid()
        shot_id = _uid()
        ch_id = _uid()
        db.add(Project(id=pid, title="t", style="国漫3D", source_text="x"))
        db.add(Chapter(id=ch_id, project_id=pid, index=0, title="一", text="x", status="storyboarded"))
        db.add(
            Shot(
                id=shot_id,
                project_id=pid,
                chapter_id=ch_id,
                order_index=0,
                scene_asset_id=old_id,
                lines_json=json.dumps([{"asset_id": old_id, "name": "林"}], ensure_ascii=False),
                slots_json=json.dumps([{"asset_id": old_id}], ensure_ascii=False),
                prop_asset_ids_json=json.dumps([old_id], ensure_ascii=False),
            )
        )
        db.commit()
        from app.services import detach_shot_asset_refs

        detach_shot_asset_refs(db, pid)
        db.commit()
        shot = db.get(Shot, shot_id)
        assert shot.scene_asset_id == ""
        assert all(not (ln.get("asset_id") or "") for ln in json.loads(shot.lines_json))
        assert all(not (s.get("asset_id") or "") for s in json.loads(shot.slots_json))
        assert json.loads(shot.prop_asset_ids_json) == []
    finally:
        db.close()


def test_run_edit_raises_when_qa_never_passes(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")

    from app.comfy_supervisor import ComfySupervisor
    from app.image_worker import ImageWorker
    from app.llm_supervisor import LlmSupervisor

    class FakeClient:
        def upload_image(self, data, name):
            return name or "ref.png"

        def queue_prompt(self, _wf):
            return "p1"

        def wait_history(self, _pid, timeout_seconds=1):
            return {}

        def collect_images(self, _hist):
            return [b"fake-png"]

    llm = LlmSupervisor(stop_cmd=lambda: None, start_cmd=lambda: None, is_up=lambda: False, settle_seconds=0)
    comfy = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=str(tmp_path / "comfy"),
        python="python",
        idle_seconds=9999,
        stop_when_idle=False,
        client_factory=lambda _url: FakeClient(),
        start_process=lambda: None,
        stop_process=lambda: None,
        is_up=lambda: True,
    )
    worker = ImageWorker(
        session_factory=database.SessionLocal,
        comfy=comfy,
        llm=llm,
        models_dir=tmp_path / "models",
    )
    monkeypatch.setattr(
        "app.comfy_pipeline.qa.assess_image_bytes",
        lambda *_a, **_k: {"ok": False, "passed": False, "reasons": ["identity"]},
    )

    db = database.SessionLocal()
    try:
        pid = _uid()
        aid = _uid()
        db.add(Project(id=pid, title="t", style="国漫3D", source_text="x"))
        db.add(Asset(id=aid, project_id=pid, kind="character", name="A", full_path="x"))
        ref = tmp_path / "ref.png"
        ref.write_bytes(b"ref")
        job = ImageJob(
            id=_uid(),
            project_id=pid,
            asset_id=aid,
            kind="edit",
            target_field="half",
            status="running",
            prompt="x",
            payload_json=json.dumps(
                {
                    "ref_paths": [str(ref)],
                    "ref_labels": ["图1"],
                    "attempts": 2,
                    "aspect": "3:4",
                    "quality": "standard",
                }
            ),
            batch_id=_uid(),
        )
        db.add(job)
        db.commit()
        with pytest.raises(RuntimeError, match="qa_failed"):
            worker._run_edit(db, FakeClient(), job, json.loads(job.payload_json))
    finally:
        db.close()


def test_cancelled_after_write_does_not_persist_first_frame(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.ollama_vram.unload_all_ollama", lambda: [])

    from app.comfy_supervisor import ComfySupervisor
    from app.image_worker import ImageWorker
    from app.llm_supervisor import LlmSupervisor

    class FakeClient:
        pass

    llm = LlmSupervisor(stop_cmd=lambda: None, start_cmd=lambda: None, is_up=lambda: False, settle_seconds=0)
    comfy = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=str(tmp_path / "comfy"),
        python="python",
        idle_seconds=9999,
        stop_when_idle=False,
        client_factory=lambda _url: FakeClient(),
        start_process=lambda: None,
        stop_process=lambda: None,
        is_up=lambda: True,
    )
    worker = ImageWorker(
        session_factory=database.SessionLocal,
        comfy=comfy,
        llm=llm,
        models_dir=tmp_path / "models",
    )

    db = database.SessionLocal()
    try:
        pid = _uid()
        cid = _uid()
        sid = _uid()
        db.add(
            Project(
                id=pid,
                title="t",
                style="国漫3D",
                source_text="x",
                image_output_dir=str(tmp_path / "out"),
            )
        )
        db.add(Chapter(id=cid, project_id=pid, index=0, title="一", text="x", status="storyboarded"))
        db.add(Shot(id=sid, project_id=pid, chapter_id=cid, order_index=0, first_frame_path=""))
        job = ImageJob(
            id=_uid(),
            project_id=pid,
            asset_id="",
            shot_id=sid,
            kind="edit",
            target_field="first_frame",
            status="queued",
            prompt="x",
            payload_json=json.dumps({"shot_id": sid}),
            batch_id=_uid(),
        )
        db.add(job)
        db.commit()
        job_id = job.id
    finally:
        db.close()

    def edit_then_cancel(db_sess, client, j, payload):
        c = database.SessionLocal()
        try:
            r = c.get(ImageJob, j.id)
            assert r is not None
            r.status = "cancelled"
            r.error = "cancelled_by_user"
            c.commit()
        finally:
            c.close()
        return b"png-bytes"

    monkeypatch.setattr(worker, "_run_edit", edit_then_cancel)
    monkeypatch.setattr(worker.comfy, "ensure_running", lambda: None)
    monkeypatch.setattr(worker, "_client", lambda: FakeClient())

    worker._process_job_id(job_id)

    check = database.SessionLocal()
    try:
        shot = check.get(Shot, sid)
        again = check.get(ImageJob, job_id)
        assert again is not None and again.status == "cancelled"
        assert (shot.first_frame_path or "") == ""
    finally:
        check.close()
