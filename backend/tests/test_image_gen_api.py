from fastapi.testclient import TestClient

from app import db as database
from app.comfy_supervisor import ComfySupervisor
from app.db import Asset, reset_engine
from app.image_worker import ImageWorker
from app.llm_supervisor import LlmSupervisor
from app.main import app
from app.services import _uid
from tests.test_image_worker import FakeComfy


def test_generate_one_asset_character_enqueues_and_worker_writes(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)
    monkeypatch.setattr(
        "app.comfy_pipeline.qa.assess_image_bytes",
        lambda *a, **k: {"ok": True, "passed": True, "reasons": []},
    )

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

    with TestClient(app) as client:
        created = client.post(
            "/api/projects",
            json={"title": "t", "text": "第一章\n林砚之站着。", "style": "半写实江湖"},
        ).json()
        pid = created["project"]["id"]
        db = database.SessionLocal()
        try:
            asset = Asset(
                id=_uid(),
                project_id=pid,
                kind="character",
                name="林砚之",
                refer_as="少年",
                desc_zh="清瘦少年，洗白长衫",
                confirmed=True,
            )
            db.add(asset)
            db.commit()
            aid = asset.id
        finally:
            db.close()

        out = client.post(f"/api/projects/{pid}/assets/{aid}/generate-image?field=full")
        assert out.status_code == 200, out.text
        body = out.json()
        assert body["job"]["kind"] == "t2i"
        assert body["job"]["target_field"] == "full"
        assert body["job"]["status"] == "queued"

        # half depends on full — enqueue half after full is written
        worker.drain_once()
        half = client.post(f"/api/projects/{pid}/assets/{aid}/generate-image?field=half")
        assert half.status_code == 200, half.text
        worker.drain_once()

        bundle = client.get(f"/api/projects/{pid}").json()
        asset_out = next(a for a in bundle["assets"] if a["id"] == aid)
        assert asset_out["full_path"]
        assert asset_out["half_path"]
        assert (tmp_path / asset_out["full_path"]).exists()
        assert (tmp_path / asset_out["half_path"]).exists()

        cleared = client.delete(f"/api/projects/{pid}/assets/{aid}/image?field=half")
        assert cleared.status_code == 200
        assert cleared.json()["half_path"] == ""
        assert cleared.json()["full_path"]  # full kept
