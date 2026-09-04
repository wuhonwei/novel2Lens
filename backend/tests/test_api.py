import json

from fastapi.testclient import TestClient

from app.db import reset_engine
from app import llm as llm_mod
from app.main import app
from app.services import _uid


SAMPLE = """第一章 雾锁渡口
林砚之站在雾里，十七岁，一身洗得发白的长衫。
陈守义坐在船头，花白头发，藏青色短打。
林砚之说：我母亲叫苏晚卿。
"""


async def fake_chat_json(messages, **_kwargs):
    system = messages[0]["content"]
    if "资产导演" in system:
        return {
            "proposals": [
                {
                    "kind": "character",
                    "action": "create",
                    "name": "林砚之",
                    "aliases": ["砚之"],
                    "refer_as": "少年",
                    "age_band": "十七岁",
                    "appearance": {"face": "眉眼清俊", "clothing": "发白长衫", "body": "清瘦"},
                    "desc_zh": "十七岁清俊少年，苍白，洗白长衫",
                    "desc_en": "pale 17-year-old scholar in faded robe",
                },
                {
                    "kind": "character",
                    "action": "create",
                    "name": "陈守义",
                    "aliases": ["陈伯", "陈老伯"],
                    "refer_as": "老者",
                    "age_band": "老年",
                    "appearance": {"face": "皱纹深", "clothing": "藏青短打"},
                    "desc_zh": "花白头发的老船工",
                    "desc_en": "elderly boatman in navy short jacket",
                },
                {
                    "kind": "scene",
                    "action": "create",
                    "name": "青川渡口",
                    "appearance": {"time": "清晨", "condition": "大雾"},
                    "desc_zh": "湿冷白雾中的青石渡口",
                    "desc_en": "foggy bluestone ferry at dawn",
                },
                {
                    "kind": "prop",
                    "action": "create",
                    "name": "苏字玉佩",
                    "desc_zh": "刻着苏字的半块玉佩",
                    "desc_en": "jade pendant carved with Su",
                },
            ]
        }, False
    return {
        "shots": [
            {
                "duration_s": 6,
                "scene_name": "青川渡口",
                "background": "",
                "camera": "固定",
                "camera_detail": "雾气微动",
                "narration": "江雾更浓了。",
                "action": "",
                "source_excerpt": "林砚之站在雾里",
                "characters": [
                    {
                        "name": "林砚之",
                        "position": "左一",
                        "facing": "朝右",
                        "transient": "",
                        "action": "递出玉佩",
                        "dialogue": "我母亲叫苏晚卿",
                        "voice_direction": "哽咽而轻",
                    },
                    {
                        "name": "陈守义",
                        "position": "右一",
                        "facing": "朝左",
                        "transient": "",
                        "action": "接过玉佩",
                        "dialogue": "",
                        "voice_direction": "",
                    },
                ],
            }
        ]
    }, False


def test_full_planner_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    monkeypatch.setattr("app.services.chat_json", fake_chat_json)
    monkeypatch.setattr(llm_mod, "chat_json", fake_chat_json)

    with TestClient(app) as client:
        created = client.post("/api/projects", json={"title": "青川渡", "text": SAMPLE, "style": "半写实江湖"}).json()
        assert len(created["chapters"]) == 1
        pid = created["project"]["id"]
        cid = created["chapters"][0]["id"]

        extracted = client.post(f"/api/projects/{pid}/chapters/{cid}/extract")
        assert extracted.status_code == 200, extracted.text
        proposals = extracted.json()["proposals"]
        assert len(proposals) == 4

        items = [{**p, "accept": True} for p in proposals]
        confirmed = client.post(f"/api/projects/{pid}/chapters/{cid}/confirm", json={"items": items}).json()
        assert len(confirmed["assets"]) == 4
        people = [a for a in confirmed["assets"] if a["kind"] == "character"]
        scene = next(a for a in confirmed["assets"] if a["kind"] == "scene")

        board = client.post(f"/api/projects/{pid}/chapters/{cid}/storyboard").json()
        assert board["shots"]
        shot = board["shots"][0]
        assert "图一为场景底板" in shot["prompt_zh"]
        assert "<Image 1>" in shot["h3_prompt"]
        assert "左一的少年" in shot["h3_prompt"]
        assert shot["character_count"] == 2
        assert "林砚之" not in shot["h3_prompt"].replace("我母亲叫苏晚卿", "")

        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        for person in people:
            client.post(
                f"/api/projects/{pid}/assets/{person['id']}/upload",
                data={"field": "half"},
                files={"file": ("half.png", png, "image/png")},
            )
            client.post(
                f"/api/projects/{pid}/assets/{person['id']}/upload",
                data={"field": "full"},
                files={"file": ("full.png", png, "image/png")},
            )
        client.post(
            f"/api/projects/{pid}/assets/{scene['id']}/upload",
            data={"field": "image"},
            files={"file": ("scene.png", png, "image/png")},
        )
        exported = client.post(f"/api/projects/{pid}/export").json()
        assert exported["document"]["h3_encoder"].startswith("qwen3vl_32b_heretic")
        assert exported["document"]["shots"]
