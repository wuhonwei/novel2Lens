"""Tests for first-frame / T2I QA payload flags and scoped readiness."""
from __future__ import annotations

from app.db import Asset, Chapter, Project, Shot, reset_engine
from app.image_jobs import _first_frame_payload, _t2i_payload
from app.serialize import serialize_chapter
from app.services import _uid
from app.storyboard_ops import _shot_mentions_asset


def test_t2i_full_sets_require_fullbody(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    p = Project(id=_uid(), title="t", style="国漫3D", source_text="x")
    a = Asset(id=_uid(), project_id=p.id, kind="character", name="林", confirmed=True)
    payload = _t2i_payload(a, p, "full", "9:16")
    assert payload.get("require_fullbody") is True


def test_first_frame_payload_sets_fullbody_and_sides():
    class S:
        id = "s1"
        character_count = 2

    payload = _first_frame_payload(S(), ["/a.png", "/b.png"], ["p1", "p2"])
    assert payload["require_fullbody"] is True
    assert payload["min_character_sides"] == 2


def test_serialize_chapter_can_omit_text():
    ch = Chapter(id="c", project_id="p", index=0, title="第一章", text="很长的正文" * 100, status="ready")
    slim = serialize_chapter(ch, include_text=False)
    assert slim["text"] == ""
    assert slim["text_len"] > 0
    full = serialize_chapter(ch, include_text=True)
    assert "很长的正文" in full["text"]


def test_shot_mentions_asset():
    shot = Shot(
        id="s",
        project_id="p",
        chapter_id="c",
        order_index=0,
        scene_asset_id="sc1",
        prop_asset_ids_json='["pr1"]',
        lines_json='[{"asset_id":"ch1"}]',
        slots_json="[]",
    )
    assert _shot_mentions_asset(shot, "ch1")
    assert _shot_mentions_asset(shot, "sc1")
    assert _shot_mentions_asset(shot, "pr1")
    assert not _shot_mentions_asset(shot, "other")
