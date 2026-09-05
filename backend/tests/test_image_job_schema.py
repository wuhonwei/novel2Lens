def test_image_job_and_scene_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    from app.db import Asset, ImageJob, Project, reset_engine, SessionLocal, ensure_schema

    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    db = SessionLocal()
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
