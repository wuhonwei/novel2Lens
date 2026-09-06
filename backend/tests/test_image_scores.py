import asyncio

import pytest

from app.db import Asset, Project
from app.image_scores import (
    clamp_score,
    clear_field_score,
    load_scores,
    score_band,
    score_project_images,
    set_field_score,
    summarize_asset_scores,
)
from app.llm import OperationCancelled
from app.services import _dump


def test_score_band():
    assert score_band(None) == "none"
    assert score_band(81) == "good"
    assert score_band(80) == "ok"
    assert score_band(60) == "ok"
    assert score_band(59) == "bad"


def test_clamp_score():
    assert clamp_score(120) == 100
    assert clamp_score(-3) == 0
    assert clamp_score("87.4") == 87


def test_clear_and_set_field_score():
    asset = Asset(
        id="a1",
        project_id="p",
        kind="character",
        name="林砚之",
        image_scores_json="{}",
        full_path="x/full.png",
        half_path="x/half.png",
    )
    set_field_score(asset, "full", 90, "像少年")
    assert load_scores(asset)["full"]["score"] == 90
    clear_field_score(asset, "full")
    assert "full" not in load_scores(asset)


def test_score_project_stops_when_cancelled(tmp_path, monkeypatch):
    from app import db as database
    from app.db import reset_engine
    from app.services import _uid

    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    calls = {"n": 0}

    async def fake_score(*, image_path, brief, chat=None, is_cancelled=None, **_kw):
        calls["n"] += 1
        return {"score": 70, "comment": "x"}

    monkeypatch.setattr("app.image_scores.score_image_file", fake_score)

    db = database.SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="s", source_text="x")
        db.add(p)
        for name in ("A", "B"):
            aid = _uid()
            rel = f"projects/{pid}/assets/{aid}/full.png"
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"png")
            db.add(
                Asset(
                    id=aid,
                    project_id=pid,
                    kind="character",
                    name=name,
                    full_path=rel,
                    half_path="",
                    image_scores_json="{}",
                )
            )
        db.commit()
        cancelled_after = {"left": 1}

        def is_cancelled():
            if cancelled_after["left"] <= 0:
                return True
            cancelled_after["left"] -= 1
            return False

        with pytest.raises(OperationCancelled):
            asyncio.run(
                score_project_images(
                    db, p, scope="assets", kind="character", is_cancelled=is_cancelled
                )
            )
        assert calls["n"] == 1
    finally:
        db.close()


def test_summarize_counts_unassessed_when_path_exists():
    assets = [
        Asset(
            id="a1",
            project_id="p",
            kind="character",
            name="A",
            full_path="f.png",
            half_path="h.png",
            image_scores_json=_dump({"full": {"score": 90, "comment": "ok"}}),
        )
    ]
    counts = summarize_asset_scores(assets, kind="character")
    assert counts["good"] == 1
    assert counts["none"] == 1  # half unscored
