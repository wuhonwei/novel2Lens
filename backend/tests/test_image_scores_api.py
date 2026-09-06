from pathlib import Path

from fastapi.testclient import TestClient

from app import db as database
from app.db import Asset, Project, reset_engine
from app.main import app
from app.services import _uid


def test_score_images_persists_and_clears_on_delete(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)
    monkeypatch.setattr("app.main._prepare_llm", lambda _db, _project=None: None)

    async def fake_score_image_file(*, image_path, brief, chat=None, **_kwargs):
        return {"score": 88, "comment": f"ok:{image_path.name}"}

    monkeypatch.setattr("app.image_scores.score_image_file", fake_score_image_file)

    db = database.SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="国漫3D", source_text="x")
        db.add(p)
        aid = _uid()
        rel = f"projects/{pid}/assets/{aid}/full.png"
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        a = Asset(
            id=aid,
            project_id=pid,
            kind="character",
            name="周大人",
            refer_as="知县",
            full_path=rel,
            half_path="",
            image_scores_json="{}",
        )
        db.add(a)
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    out = client.post(f"/api/projects/{pid}/score-images", json={"scope": "assets", "kind": "character"})
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["scored"] == 1
    assert body["asset_counts"]["good"] == 1
    asset = next(x for x in body["assets"] if x["id"] == aid)
    assert asset["image_scores"]["full"]["score"] == 88

    cleared = client.delete(f"/api/projects/{pid}/assets/{aid}/image?field=full")
    assert cleared.status_code == 200
    assert cleared.json().get("image_scores", {}) == {} or "full" not in cleared.json().get("image_scores", {})
