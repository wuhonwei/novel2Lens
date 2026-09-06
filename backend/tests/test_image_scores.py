from app.image_scores import (
    clamp_score,
    clear_field_score,
    load_scores,
    score_band,
    set_field_score,
    summarize_asset_scores,
)
from app.db import Asset, Project
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
