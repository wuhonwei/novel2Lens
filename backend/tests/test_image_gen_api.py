from fastapi.testclient import TestClient

from app.db import Asset, SessionLocal, reset_engine
from app.main import app
from app.services import _uid


def test_generate_one_asset_character_mocked(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")

    class FakeZX:
        def __init__(self, *a, **k):
            pass

        def health(self):
            return {"ok": True}

        def create_generate(self, payload):
            assert payload["aspect"] == "9:16"
            return {"id": "g1"}

        def create_edit(self, **kwargs):
            assert kwargs["aspect"] == "3:4"
            return {"id": "e1"}

        def wait_job(self, job_id, **k):
            return {"id": job_id, "status": "succeeded", "images": [{"id": f"img-{job_id}", "role": "success"}]}

        def first_success_image_id(self, job):
            return job["images"][0]["id"]

        def download_image(self, image_id):
            return b"\x89PNG\r\n\x1a\n" + image_id.encode()

    monkeypatch.setattr("app.image_gen.ZaoxiangClient", FakeZX)

    with TestClient(app) as client:
        created = client.post(
            "/api/projects",
            json={"title": "t", "text": "第一章\n林砚之站着。", "style": "半写实江湖"},
        ).json()
        pid = created["project"]["id"]
        db = SessionLocal()
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

        out = client.post(f"/api/projects/{pid}/assets/{aid}/generate-image")
        assert out.status_code == 200, out.text
        body = out.json()
        assert body["full_path"]
        assert body["half_path"]
        assert (tmp_path / body["full_path"]).exists()
        assert (tmp_path / body["half_path"]).exists()

        cleared = client.delete(f"/api/projects/{pid}/assets/{aid}/image?field=half")
        assert cleared.status_code == 200
        assert cleared.json()["half_path"] == ""
        assert cleared.json()["full_path"]  # full kept
