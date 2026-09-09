from pathlib import Path

from app import db as database
from app.db import Chapter, Project, Shot, reset_engine
from app.serialize import serialize_shot
from app.video_jobs import enqueue_chapter_videos, enqueue_shot_video


def _project_with_shot(tmp_path, monkeypatch, *, frame: bool = True, prompt: bool = True, video: bool = False):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    db = database.SessionLocal()
    project = Project(id="p1", title="t", style="写实电影", source_text="x")
    chapter = Chapter(id="c1", project_id="p1", index=0, title="一", text="x")
    shot = Shot(
        id="s1",
        project_id="p1",
        chapter_id="c1",
        order_index=1,
        duration_s=6.0,
        h3_prompt="缓慢推近" if prompt else "",
        first_frame_path="projects/p1/shots/s1/first_frame.png" if frame else "",
        video_path="projects/p1/shots/s1/video.mp4" if video else "",
    )
    db.add_all([project, chapter, shot])
    db.commit()
    if frame:
        path = tmp_path / "projects" / "p1" / "shots" / "s1" / "first_frame.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake")
    return db, project, shot


def test_enqueue_shot_video_requires_first_frame(tmp_path, monkeypatch):
    db, project, shot = _project_with_shot(tmp_path, monkeypatch, frame=False)
    try:
        try:
            enqueue_shot_video(db, project, shot)
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "首帧" in str(exc)
    finally:
        db.close()


def test_enqueue_shot_video_requires_h3_prompt(tmp_path, monkeypatch):
    db, project, shot = _project_with_shot(tmp_path, monkeypatch, prompt=False)
    try:
        try:
            enqueue_shot_video(db, project, shot)
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "H3" in str(exc) or "提示" in str(exc)
    finally:
        db.close()


def test_enqueue_shot_video_ok(tmp_path, monkeypatch):
    db, project, shot = _project_with_shot(tmp_path, monkeypatch)
    try:
        job = enqueue_shot_video(db, project, shot)
        assert job.status == "queued"
        assert job.shot_id == shot.id
        assert "缓慢推近" in job.prompt
    finally:
        db.close()


def test_chapter_skips_existing_video_unless_overwrite(tmp_path, monkeypatch):
    db, project, _shot = _project_with_shot(tmp_path, monkeypatch, video=True)
    try:
        result = enqueue_chapter_videos(db, project, "c1", overwrite=False)
        assert result["queued"] == 0
        assert result["skipped"]
        result2 = enqueue_chapter_videos(db, project, "c1", overwrite=True)
        assert result2["queued"] == 1
    finally:
        db.close()


def test_serialize_shot_includes_video_path(tmp_path, monkeypatch):
    db, _project, shot = _project_with_shot(tmp_path, monkeypatch, video=True)
    try:
        doc = serialize_shot(shot)
        assert doc["video_path"].endswith("video.mp4")
        assert "video_version" in doc
    finally:
        db.close()
