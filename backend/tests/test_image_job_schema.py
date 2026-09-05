from app import db as database
from app.db import Asset, ImageJob, Project, reset_engine
from app.services import serialize_asset


def test_image_job_and_scene_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    db = database.SessionLocal()
    p = Project(id="p1", title="t", style="", source_text="x")
    db.add(p)
    a = Asset(id="a1", project_id="p1", kind="scene", name="渡口", far_path="", near_path="")
    db.add(a)
    j = ImageJob(
        id="j1",
        project_id="p1",
        asset_id="a1",
        kind="t2i",
        target_field="far",
        status="queued",
        phase="",
        prompt="fog pier",
        payload_json="{}",
        batch_id="b1",
        error="",
    )
    db.add(j)
    db.commit()
    row = db.get(ImageJob, "j1")
    assert row.status == "queued"
    assert hasattr(db.get(Asset, "a1"), "far_path")


def test_serialize_asset_legacy_image_path_fallback():
    asset = Asset(
        id="a1",
        project_id="p1",
        kind="scene",
        name="渡口",
        far_path="",
        near_path="",
        image_path="/data/scenes/pier.png",
    )
    out = serialize_asset(asset)
    assert out["far_path"] == "/data/scenes/pier.png"
