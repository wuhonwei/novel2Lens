# -*- coding: utf-8 -*-
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import db as database
from app.db import Chapter, Project, Shot, reset_engine
from app.main import app
from app.services import _uid


def test_score_videos_persists_and_clears_on_enqueue(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    monkeypatch.setattr("app.config.settings.video_qa_auto_regen", False)
    monkeypatch.setattr("app.config.settings.video_qa_frame_count", 2)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)
    monkeypatch.setattr("app.main._start_video_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_video_worker", lambda: None)
    monkeypatch.setattr("app.main._prepare_llm", lambda _db, _project=None: None)

    async def fake_score_image_file(*, image_path, brief, chat=None, **_kwargs):
        return {"score": 80, "comment": f"frame:{Path(image_path).name}"}

    def fake_keyframes(video, work, count=None):
        work = Path(work)
        work.mkdir(parents=True, exist_ok=True)
        outs = []
        for i in range(int(count or 2)):
            p = work / f"frame_{i:02d}.png"
            Image.new("RGB", (32, 18), (40, 80, 120)).save(p)
            outs.append(p)
        return outs

    def fake_wav(video, wav):
        Path(wav).parent.mkdir(parents=True, exist_ok=True)
        Path(wav).write_bytes(b"RIFF")
        return Path(wav)

    monkeypatch.setattr("app.video_scores.score_image_file", fake_score_image_file)
    monkeypatch.setattr("app.video_scores.extract_keyframes", fake_keyframes)
    monkeypatch.setattr("app.video_scores.extract_wav", fake_wav)
    monkeypatch.setattr("app.video_scores.asr_available", lambda: True)
    monkeypatch.setattr("app.video_scores.transcribe_wav", lambda _w: "请问是陈守义老伯吗")

    pid = _uid()
    cid = _uid()
    sid = _uid()
    rel = f"projects/{pid}/shots/{sid}/video.mp4"
    vpath = tmp_path / rel
    vpath.parent.mkdir(parents=True, exist_ok=True)
    vpath.write_bytes(b"fake-mp4")
    frame_rel = f"projects/{pid}/shots/{sid}/first_frame.png"
    fpath = tmp_path / frame_rel
    Image.new("RGB", (64, 36), (20, 40, 60)).save(fpath)

    db = database.SessionLocal()
    try:
        db.add(Project(id=pid, title="t", style="国风3D", source_text="x"))
        db.add(Chapter(id=cid, project_id=pid, index=0, title="一", text="x"))
        db.add(
            Shot(
                id=sid,
                project_id=pid,
                chapter_id=cid,
                order_index=1,
                duration_s=6.0,
                h3_prompt="左一的少年，开口说道：「请问，是陈守义老伯吗？」。 旁白（画外音）：无",
                first_frame_path=frame_rel,
                video_path=rel,
                lines_json='[{"name":"林砚之","dialogue":"请问，是陈守义老伯吗？"}]',
            )
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    out = client.post(
        f"/api/projects/{pid}/score-videos",
        json={"scope": "chapter", "chapter_id": cid},
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["scored"] == 1
    shot = next(s for s in body["shots"] if s["id"] == sid)
    assert shot["video_score"] is not None
    assert shot["video_score"] >= 60
    assert shot["video_qa"]["speech_expected"] is True
    assert "请问" in (shot["video_qa"].get("transcript") or "")

    # Enqueue overwrite clears score
    enq = client.post(f"/api/projects/{pid}/shots/{sid}/generate-video?overwrite=true")
    assert enq.status_code == 200, enq.text
    shot2 = next(s for s in enq.json()["shots"] if s["id"] == sid)
    assert shot2["video_score"] is None
