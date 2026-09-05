from fastapi.testclient import TestClient

from app.db import reset_engine
from app import llm as llm_mod
from app.main import app

NOVEL = """青川渡
第一章 雾锁渡口
林砚之站在雾里，十七岁，一身洗得发白的长衫。
陈守义坐在船头，花白头发，藏青色短打。
林砚之递出苏字玉佩。
"""

PASS1 = {
    "人物": [  # Chinese key must still map to character
        {"name": "林砚之", "aliases": ["砚之"], "refer_as": "少年", "age_band": "十七岁", "notes": ""},
        {"name": "陈守义", "aliases": ["陈伯"], "refer_as": "老者", "notes": "老船工"},
    ],
    "scenes": [{"name": "青川渡口", "notes": "晨雾渡口"}],
    "核心物品": [{"name": "苏字玉佩", "notes": ""}],
}

PASS2 = {
    "complete": False,
    "missing": [
        {
            "kind": "character",
            "name": "林砚之",
            "action": "supplement",
            "desc_zh": "眉眼清俊，脸色苍白，洗白长衫",
            "appearance": {"face": "眉眼清俊", "clothing": "发白长衫"},
        },
        {
            "kind": "prop",
            "name": "苏字玉佩",
            "action": "supplement",
            "desc_zh": "半块玉佩，刻着苏字",
        },
    ],
    "new_items": [],
}

PASS3 = {"complete": True, "missing": [], "new_items": []}


async def fake_chat_json(messages, **_kwargs):
    text = "\n".join(m.get("content", "") for m in messages)
    if "完整性审计" in text or "第二遍" in text or "查漏补缺" in text:
        if "眉眼清俊" in text or "半块玉佩" in text:
            return PASS3, False
        return PASS2, False
    if "登记总表" in text or "第一遍" in text or "登记员" in text or "通读材料" in text:
        return PASS1, False
    return {"proposals": []}, False


def test_one_click_generate_book_assets(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 'scan.sqlite'}")
    monkeypatch.setattr("app.services.chat_json", fake_chat_json)
    monkeypatch.setattr(llm_mod, "chat_json", fake_chat_json)

    with TestClient(app) as client:
        files = {"file": ("qing.txt", NOVEL.encode("utf-8"), "text/plain")}
        res = client.post(
            "/api/projects/upload",
            data={"title": "青川渡", "style": "半写实江湖"},
            files=files,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["assets"] == []
        pid = body["project"]["id"]

        gen = client.post(f"/api/projects/{pid}/generate-assets?replace=true")
        assert gen.status_code == 200, gen.text
        body = gen.json()
        assets = body["assets"]
        kinds = {a["kind"] for a in assets}
        assert "character" in kinds
        assert "scene" in kinds
        assert "prop" in kinds
        chars = [a for a in assets if a["kind"] == "character"]
        assert len(chars) >= 2
        assert all(a["confirmed"] for a in assets)
        lin = next(a for a in assets if a["name"] == "林砚之")
        assert lin["kind"] == "character"
        assert "眉眼清俊" in lin["desc_zh"]
        prop = next(a for a in assets if a["name"] == "苏字玉佩")
        assert prop["kind"] == "prop"
        assert prop["half_path"] == ""
        assert prop["full_path"] == ""
        scan = body.get("result") or body["project"].get("registry_scan")
        assert isinstance(scan, dict) and len(scan.get("passes") or []) >= 2
        assert all(c.get("prescan_done") for c in body["chapters"])
        assert all(c["status"] == "assets_confirmed" for c in body["chapters"])
