from app.domain.shot_refs import build_shot_references


class _A:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_build_shot_references_lists_scene_full_half_and_missing():
    scene = _A(id="s1", kind="scene", name="青川渡", image_path="", half_path="", full_path="")
    char = _A(id="c1", kind="character", name="林砚之", image_path="", half_path="h.png", full_path="")
    slots = [
        {"index": 1, "kind": "scene", "asset_id": "s1", "image_key": "scene"},
        {"index": 2, "kind": "character", "asset_id": "c1", "image_key": "full", "position": "中"},
        {"index": 3, "kind": "character", "asset_id": "c1", "image_key": "half", "position": "中"},
    ]
    refs = build_shot_references(
        scene=scene,
        lines=[{"asset_id": "c1", "position": "中"}],
        slots=slots,
        props=[],
        half_lock=True,
        assets_by_id={"s1": scene, "c1": char},
    )
    assert refs[0]["image_role"] == "核心场景参考图"
    assert refs[0]["uploaded"] is False
    assert refs[0]["status_zh"] == "尚未上传"
    assert refs[0]["slot_index"] == 1
    full = next(r for r in refs if r["image_key"] == "full")
    half = next(r for r in refs if r["image_key"] == "half")
    assert full["asset_name"] == "林砚之"
    assert full["uploaded"] is False
    assert half["uploaded"] is True
    assert half["note"] == "锁脸"


def test_build_shot_references_includes_prop_even_without_slot():
    prop = _A(id="p1", kind="prop", name="半块玉佩", image_path="p.png", half_path="", full_path="")
    char = _A(id="c1", kind="character", name="林砚之", image_path="", half_path="h.png", full_path="f.png")
    refs = build_shot_references(
        scene=None,
        lines=[{"asset_id": "c1", "position": "中"}],
        slots=[{"index": 1, "kind": "character", "asset_id": "c1", "image_key": "full", "position": "中"}],
        props=[prop],
        half_lock=False,
        assets_by_id={"c1": char, "p1": prop},
    )
    roles = [r["image_role"] for r in refs]
    assert "人物全身图" in roles
    assert "人物半身图" in roles  # required even if not in Qwen slots
    assert "核心物品参考图" in roles
    prop_ref = next(r for r in refs if r["image_key"] == "prop")
    assert prop_ref["uploaded"] is True
    assert prop_ref["asset_name"] == "半块玉佩"
