from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _project() -> str:
    r = client.post("/api/projects", json={"title": "manual-asset", "style": "国漫3D", "source_text": "甲乙丙"})
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


def test_create_character_scene_prop_assets():
    pid = _project()
    c = client.post(
        f"/api/projects/{pid}/assets",
        json={"kind": "character", "name": "林砚之", "desc_zh": "男，青年，清瘦，青衫白袖"},
    )
    assert c.status_code == 200, c.text
    assert c.json()["kind"] == "character"
    assert c.json()["name"] == "林砚之"
    assert c.json()["desc_zh"]

    s = client.post(
        f"/api/projects/{pid}/assets",
        json={"kind": "scene", "name": "青川渡", "desc_zh": "雾中青石渡口"},
    )
    assert s.status_code == 200, s.text
    assert s.json()["kind"] == "scene"

    p = client.post(
        f"/api/projects/{pid}/assets",
        json={"kind": "prop", "name": "苏字玉佩", "desc_zh": "半块刻苏字的玉佩"},
    )
    assert p.status_code == 200, p.text
    assert p.json()["kind"] == "prop"


def test_create_asset_duplicate_name_same_kind_409():
    pid = _project()
    body = {"kind": "prop", "name": "玉佩", "desc_zh": "半块玉"}
    assert client.post(f"/api/projects/{pid}/assets", json=body).status_code == 200
    r = client.post(f"/api/projects/{pid}/assets", json=body)
    assert r.status_code == 409


def test_create_asset_rejects_empty():
    pid = _project()
    r = client.post(f"/api/projects/{pid}/assets", json={"kind": "scene", "name": "", "desc_zh": "x"})
    assert r.status_code == 400
