from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db import reset_engine
from app.main import app
from app import llm as llm_mod
from app.services import asset_ref_ready, missing_asset_image_messages, require_asset_images


def _ns(**kw):
    base = dict(
        kind="character",
        name="x",
        half_path="",
        full_path="",
        far_path="",
        near_path="",
        image_path="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_asset_ref_ready_rules():
    assert asset_ref_ready(_ns(kind="character", half_path="h", full_path="f"))
    assert not asset_ref_ready(_ns(kind="character", half_path="h", full_path=""))
    assert asset_ref_ready(_ns(kind="scene", near_path="n"))
    assert asset_ref_ready(_ns(kind="scene", far_path="f"))
    assert asset_ref_ready(_ns(kind="scene", image_path="legacy"))
    assert not asset_ref_ready(_ns(kind="scene"))
    assert asset_ref_ready(_ns(kind="prop", image_path="i"))
    assert not asset_ref_ready(_ns(kind="prop"))


def test_require_asset_images_raises_chinese():
    assets = [
        _ns(kind="character", name="林砚之", half_path="", full_path=""),
        _ns(kind="scene", name="渡口"),
        _ns(kind="prop", name="玉佩"),
    ]
    msgs = missing_asset_image_messages(assets)
    assert any("林砚之" in m for m in msgs)
    assert any("渡口" in m for m in msgs)
    assert any("玉佩" in m for m in msgs)
    with pytest.raises(ValueError, match="参考图未齐备"):
        require_asset_images(assets)


def test_require_asset_images_ok_when_complete():
    assets = [
        _ns(kind="character", name="林砚之", half_path="h", full_path="f"),
        _ns(kind="scene", name="渡口", near_path="n"),
        _ns(kind="prop", name="玉佩", image_path="p"),
    ]
    require_asset_images(assets)


SAMPLE = "第一章 雾\n林砚之站在青川渡口，递出苏字玉佩给陈守义。"


async def _fake_chat_json(messages, **kwargs):
    text = messages[-1]["content"] if messages else ""
    if "shots" in text.lower() or "分镜" in text or "镜头" in text:
        return {
            "shots": [
                {
                    "duration_s": 6,
                    "scene_name": "青川渡口",
                    "background": "",
                    "camera": "固定",
                    "camera_detail": "",
                    "narration": "雾。",
                    "action": "",
                    "source_excerpt": "林砚之",
                    "characters": [
                        {
                            "name": "林砚之",
                            "position": "中",
                            "facing": "面向镜头",
                            "transient": "",
                            "action": "",
                            "dialogue": "",
                            "voice_direction": "",
                        }
                    ],
                }
            ]
        }, False
    return {
        "characters": [
            {
                "action": "create",
                "name": "林砚之",
                "desc_zh": "少年",
                "desc_en": "youth",
                "aliases": [],
                "refer_as": "少年",
                "age_band": "青年",
                "appearance": {},
            }
        ],
        "scenes": [{"action": "create", "name": "青川渡口", "desc_zh": "渡口", "desc_en": "ferry"}],
        "props": [{"action": "create", "name": "苏字玉佩", "desc_zh": "玉佩", "desc_en": "pendant"}],
    }, False


def test_storyboard_409_without_images(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.services.chat_json", _fake_chat_json)
    monkeypatch.setattr(llm_mod, "chat_json", _fake_chat_json)
    monkeypatch.setattr("app.main._start_image_worker", lambda: None)
    monkeypatch.setattr("app.main._stop_image_worker", lambda: None)

    with TestClient(app) as client:
        created = client.post(
            "/api/projects",
            json={"title": "闸门测", "text": SAMPLE, "style": "国风3D"},
        ).json()
        pid = created["project"]["id"]
        cid = created["chapters"][0]["id"]
        gen = client.post(f"/api/projects/{pid}/generate-assets?replace=true")
        assert gen.status_code == 200, gen.text
        board = client.post(f"/api/projects/{pid}/chapters/{cid}/storyboard")
        assert board.status_code == 409
        assert "参考图未齐备" in board.json()["detail"]
