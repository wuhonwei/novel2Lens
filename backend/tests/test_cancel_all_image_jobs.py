from fastapi.testclient import TestClient

from app.db import ImageJob, SessionLocal
from app.image_jobs import ACTIVE_STATUSES
from app.main import app
from app.serialize import _uid


client = TestClient(app)


def test_cancel_all_image_jobs_unlocks_llm():
    r = client.post("/api/projects", json={"title": "cancel-all-a", "style": "国漫3D", "source_text": "甲"})
    assert r.status_code == 200
    pid = r.json()["project"]["id"]
    db = SessionLocal()
    try:
        for _ in range(2):
            db.add(
                ImageJob(
                    id=_uid(),
                    project_id=pid,
                    asset_id="",
                    shot_id="",
                    kind="edit",
                    target_field="first_frame",
                    status="queued",
                    phase="",
                    prompt="x",
                    payload_json="{}",
                    error="",
                    batch_id="",
                )
            )
        db.commit()
    finally:
        db.close()

    blocked = client.post(f"/api/projects/{pid}/generate-assets", params={"replace": False})
    assert blocked.status_code == 409
    assert "参考图生成中" in blocked.json()["detail"]

    cancelled = client.post("/api/image-jobs/cancel-all")
    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] >= 2

    db = SessionLocal()
    try:
        assert db.query(ImageJob).filter(ImageJob.status.in_(ACTIVE_STATUSES)).count() == 0
    finally:
        db.close()
