"""ImageWorker + enqueue API — FakeComfy, no real GPU."""
from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from app import db as database
from app.db import Asset, Chapter, ImageJob, Project, reset_engine
from app.main import app
from app.services import _uid


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeComfy:
    """Minimal Comfy stand-in: returns tiny PNG, optional sleep for serial test."""

    def __init__(self, sleep_s: float = 0.0):
        self.sleep_s = sleep_s
        self.queue_calls = 0
        self.free_calls = 0
        self._lock = threading.Lock()
        self.concurrent_running = 0
        self.max_concurrent = 0

    def health(self):
        return {"ok": True, "checkpoints": [], "checkpoint_count": 0}

    def list_checkpoints(self):
        return ["RealVisXL_V5.0_fp16.safetensors"]

    def free_memory(self, **_kwargs):
        self.free_calls += 1

    def upload_image(self, data: bytes, filename: str) -> str:
        return filename

    def queue_prompt(self, prompt, client_id=None) -> str:
        with self._lock:
            self.concurrent_running += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent_running)
            self.queue_calls += 1
            pid = f"p{self.queue_calls}"
        if self.sleep_s:
            time.sleep(self.sleep_s)
        with self._lock:
            self.concurrent_running -= 1
        return pid

    def wait_history(self, prompt_id: str, timeout_seconds: float = 600.0):
        return {
            "outputs": {
                "9": {"images": [{"filename": f"{prompt_id}.png", "subfolder": "", "type": "output"}]}
            }
        }

    def collect_images(self, history_entry):
        return [TINY_PNG]

    def interrupt(self):
        pass


def _seed_project(db, *, with_chapter: bool = False):
    pid = _uid()
    p = Project(id=pid, title="t", style="半写实江湖", source_text="第一章\n林砚之站着。")
    db.add(p)
    char = Asset(
        id=_uid(),
        project_id=pid,
        kind="character",
        name="林砚之",
        desc_zh="清瘦少年，洗白长衫",
        confirmed=True,
    )
    scene = Asset(
        id=_uid(),
        project_id=pid,
        kind="scene",
        name="青川渡口",
        desc_zh="湿冷白雾中的青石渡口",
        confirmed=True,
    )
    prop = Asset(
        id=_uid(),
        project_id=pid,
        kind="prop",
        name="苏字玉佩",
        desc_zh="刻着苏字的半块玉佩",
        confirmed=True,
    )
    db.add_all([char, scene, prop])
    if with_chapter:
        ch = Chapter(
            id=_uid(),
            project_id=pid,
            index=0,
            title="第一章",
            text="林砚之站着。",
            status="ready",
        )
        db.add(ch)
        db.commit()
        return p, char, scene, prop, ch
    db.commit()
    return p, char, scene, prop


def test_one_click_orders_t2i_before_edit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")

    from app.comfy_supervisor import ComfySupervisor
    from app.image_jobs import enqueue_one_click
    from app.image_worker import ImageWorker
    from app.llm_supervisor import LlmSupervisor

    fake = FakeComfy()
    llm = LlmSupervisor(stop_cmd=lambda: None, start_cmd=lambda: None, is_up=lambda: False, settle_seconds=0)
    comfy = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=str(tmp_path / "comfy"),
        python="python",
        idle_seconds=9999,
        stop_when_idle=False,
        client_factory=lambda _url: fake,
        start_process=lambda: None,
        stop_process=lambda: None,
        is_up=lambda: True,
    )

    db = database.SessionLocal()
    try:
        project, *_ = _seed_project(db)
        result = enqueue_one_click(db, project)
        assert result["batch_id"]
        assert len(result["job_ids"]) == 5

        jobs = db.query(ImageJob).order_by(ImageJob.created_at).all()
        kinds = [j.kind for j in jobs]
        assert kinds == ["t2i", "t2i", "t2i", "edit", "edit"]
        fields = [j.target_field for j in jobs]
        assert fields == ["full", "far", "image", "half", "near"]
        assert all(j.target_field for j in jobs)

        worker = ImageWorker(
            session_factory=database.SessionLocal,
            comfy=comfy,
            llm=llm,
            poll_interval=0.05,
            models_dir=tmp_path / "models",
        )
        worker.drain_once()
        db.expire_all()
        jobs2 = db.query(ImageJob).order_by(ImageJob.created_at).all()
        assert all(j.status == "succeeded" for j in jobs2), [(j.target_field, j.status, j.error) for j in jobs2]
        # 3 T2I + 2 edit jobs; each edit may queue Lightning then non-Lightning when QA rejects tiny PNG
        assert fake.queue_calls in (5, 7)
    finally:
        db.close()


def test_llm_route_409_while_job_queued(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)

    db = database.SessionLocal()
    try:
        project, char, _scene, _prop, chapter = _seed_project(db, with_chapter=True)
        job = ImageJob(
            id=_uid(),
            project_id=project.id,
            asset_id=char.id,
            kind="t2i",
            target_field="full",
            status="queued",
            phase="",
            prompt="x",
            payload_json="{}",
            batch_id=_uid(),
            error="",
        )
        db.add(job)
        db.commit()
        pid = project.id
        cid = chapter.id
    finally:
        db.close()

    with TestClient(app) as client:
        for path in (
            f"/api/projects/{pid}/chapters/{cid}/extract",
            f"/api/projects/{pid}/chapters/{cid}/storyboard",
            f"/api/projects/{pid}/prescan",
            f"/api/projects/{pid}/generate-assets",
        ):
            r = client.post(path)
            assert r.status_code == 409, f"{path} -> {r.status_code} {r.text}"
            assert "参考图生成中" in r.json()["detail"]


def test_enqueue_asset_all_slots_orders_t2i_then_edit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")

    from app.image_jobs import enqueue_asset_all_slots

    db = database.SessionLocal()
    try:
        project, char, scene, prop = _seed_project(db)

        char_jobs = enqueue_asset_all_slots(db, project, char)
        assert [j.kind for j in char_jobs] == ["t2i", "edit"]
        assert [j.target_field for j in char_jobs] == ["full", "half"]

        scene_jobs = enqueue_asset_all_slots(db, project, scene)
        assert [j.kind for j in scene_jobs] == ["t2i", "edit"]
        assert [j.target_field for j in scene_jobs] == ["far", "near"]

        prop_jobs = enqueue_asset_all_slots(db, project, prop)
        assert [j.kind for j in prop_jobs] == ["t2i"]
        assert [j.target_field for j in prop_jobs] == ["image"]
    finally:
        db.close()


def test_generate_image_field_none_enqueues_all_slots(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)

    db = database.SessionLocal()
    try:
        project, char, scene, prop = _seed_project(db)
        pid = project.id
        char_id, scene_id, prop_id = char.id, scene.id, prop.id
    finally:
        db.close()

    with TestClient(app) as client:
        char_out = client.post(f"/api/projects/{pid}/assets/{char_id}/generate-image")
        assert char_out.status_code == 200, char_out.text
        body = char_out.json()
        assert len(body["jobs"]) == 2
        assert [j["target_field"] for j in body["jobs"]] == ["full", "half"]
        assert [j["kind"] for j in body["jobs"]] == ["t2i", "edit"]

        scene_out = client.post(f"/api/projects/{pid}/assets/{scene_id}/generate-image")
        assert scene_out.status_code == 200, scene_out.text
        assert [j["target_field"] for j in scene_out.json()["jobs"]] == ["far", "near"]

        prop_out = client.post(f"/api/projects/{pid}/assets/{prop_id}/generate-image")
        assert prop_out.status_code == 200, prop_out.text
        assert [j["target_field"] for j in prop_out.json()["jobs"]] == ["image"]


def test_save_skips_when_db_already_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")

    from app.comfy_supervisor import ComfySupervisor
    from app.image_worker import ImageWorker
    from app.llm_supervisor import LlmSupervisor

    fake = FakeComfy()
    llm = LlmSupervisor(stop_cmd=lambda: None, start_cmd=lambda: None, is_up=lambda: False, settle_seconds=0)
    comfy = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=str(tmp_path / "comfy"),
        python="python",
        idle_seconds=9999,
        stop_when_idle=False,
        client_factory=lambda _url: fake,
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
        project, char, *_ = _seed_project(db)
        job = ImageJob(
            id=_uid(),
            project_id=project.id,
            asset_id=char.id,
            kind="t2i",
            target_field="full",
            status="running",
            phase="generating",
            prompt="x",
            payload_json="{}",
            batch_id=_uid(),
            error="",
        )
        db.add(job)
        db.commit()
        job_id = job.id
    finally:
        db.close()

    # Cancel from a separate session (simulates API cancel race)
    cancel_db = database.SessionLocal()
    try:
        row = cancel_db.get(ImageJob, job_id)
        assert row is not None
        row.status = "cancelled"
        row.error = "cancelled_by_user"
        cancel_db.commit()
    finally:
        cancel_db.close()

    work_db = database.SessionLocal()
    try:
        job = work_db.get(ImageJob, job_id)
        assert job is not None
        # Worker about to overwrite with succeeded
        job.status = "succeeded"
        job.phase = ""
        job.error = ""
        ok = worker._save(work_db, job)
        assert ok is False
        work_db.expire_all()
        again = work_db.get(ImageJob, job_id)
        assert again is not None
        assert again.status == "cancelled"
        assert again.error == "cancelled_by_user"
    finally:
        work_db.close()


def test_worker_serial_never_two_running(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")

    from app.comfy_supervisor import ComfySupervisor
    from app.image_jobs import enqueue_one_click
    from app.image_worker import ImageWorker
    from app.llm_supervisor import LlmSupervisor

    fake = FakeComfy(sleep_s=0.15)
    llm = LlmSupervisor(stop_cmd=lambda: None, start_cmd=lambda: None, is_up=lambda: False, settle_seconds=0)
    comfy = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=str(tmp_path / "comfy"),
        python="python",
        idle_seconds=9999,
        stop_when_idle=False,
        client_factory=lambda _url: fake,
        start_process=lambda: None,
        stop_process=lambda: None,
        is_up=lambda: True,
    )

    db = database.SessionLocal()
    try:
        project, *_ = _seed_project(db)
        enqueue_one_click(db, project)
    finally:
        db.close()

    worker = ImageWorker(
        session_factory=database.SessionLocal,
        comfy=comfy,
        llm=llm,
        poll_interval=0.02,
        models_dir=tmp_path / "models",
    )
    worker.drain_once()
    assert fake.max_concurrent == 1
    # 3 T2I + 2 edits (×1 or ×2 attempts if QA rejects tiny PNG)
    assert fake.queue_calls in (5, 7)
    # Light strengthening: every job finished succeeded under serial drain
    db = database.SessionLocal()
    try:
        statuses = [j.status for j in db.query(ImageJob).all()]
        assert statuses == ["succeeded"] * 5
    finally:
        db.close()
