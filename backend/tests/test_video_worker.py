"""VideoWorker drain with a fake H3 client (no real Comfy)."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app import db as database
from app.db import Chapter, Project, Shot, VideoJob, reset_engine
from app.video_jobs import enqueue_shot_video
from app.video_worker import VideoWorker


class FakeH3Client:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.uploaded: list[str] = []
        self.last_prompt = ""

    def upload_image(self, path: Path, *, overwrite: bool = True) -> str:
        self.uploaded.append(path.name)
        return path.name

    def queue_prompt(self, workflow: dict, client_id: str) -> str:
        assert workflow["9"]["class_type"] == "MiniMaxH3ImageToVideo"
        self.last_prompt = workflow["9"]["inputs"]["prompt"]
        return "prompt-1"

    def wait_for_prompt(self, prompt_id: str, timeout_s: float | None = None) -> dict:
        out = self.output_root / "video" / "fake.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake-mp4")
        return {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {
                "18": {"videos": [{"filename": "fake.mp4", "subfolder": "video"}]},
            },
        }

    def extract_video_path(self, history: dict, output_root: Path) -> Path:
        return output_root / "video" / "fake.mp4"


def test_video_worker_writes_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    shared_out = tmp_path / "h3_out"
    shared_out.mkdir()
    monkeypatch.setattr("app.config.settings.h3_shared_output", str(shared_out))
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    scheduled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.video_scores.schedule_score_after_video",
        lambda pid, sid: scheduled.append((pid, sid)),
    )

    frame_rel = "projects/p1/shots/s1/first_frame.png"
    frame_abs = tmp_path / frame_rel
    frame_abs.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 36), (20, 40, 60)).save(frame_abs)

    db = database.SessionLocal()
    try:
        project = Project(id="p1", title="t", style="写实电影", source_text="x")
        chapter = Chapter(id="c1", project_id="p1", index=0, title="一", text="x")
        shot = Shot(
            id="s1",
            project_id="p1",
            chapter_id="c1",
            order_index=1,
            duration_s=6.0,
            h3_prompt="缓慢推近",
            first_frame_path=frame_rel,
        )
        db.add_all([project, chapter, shot])
        db.commit()
        job = enqueue_shot_video(db, project, shot)
        job_id = job.id
    finally:
        db.close()

    fake = FakeH3Client(shared_out)
    worker = VideoWorker(
        session_factory=database.SessionLocal,
        ensure_comfy=lambda: {"status": "ok"},
        client_factory=lambda: fake,
    )
    assert worker.drain_once() == 1

    db = database.SessionLocal()
    try:
        job = db.get(VideoJob, job_id)
        shot = db.get(Shot, "s1")
        assert job is not None and job.status == "succeeded"
        assert shot is not None and shot.video_path.endswith("video.mp4")
        payload = json.loads(job.payload_json)
        assert payload.get("result_path") == shot.video_path
        assert (tmp_path / shot.video_path).is_file()
        assert "禁止日语" in fake.last_prompt
        assert "无人声" in fake.last_prompt
        assert scheduled == [("p1", "s1")]
    finally:
        db.close()


def test_schedule_score_after_video_respects_flag(monkeypatch):
    from app.video_scores import schedule_score_after_video

    monkeypatch.setattr("app.config.settings.video_qa_auto_after_video", False)
    called: list[str] = []

    class FakeThread:
        def __init__(self, *a, **k):
            called.append("thread")

        def start(self):
            called.append("start")

    monkeypatch.setattr("threading.Thread", FakeThread)
    schedule_score_after_video("p1", "s1")
    assert called == []

    monkeypatch.setattr("app.config.settings.video_qa_auto_after_video", True)
    schedule_score_after_video("p1", "s1")
    assert called == ["thread", "start"]
