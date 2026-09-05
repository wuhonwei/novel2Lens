from app.domain.shot_refs import build_shot_references, scene_image_path


class _A:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_scene_image_path_prefers_near_then_far_then_legacy():
    assert scene_image_path(_A(near_path="near.png", far_path="far.png", image_path="legacy.png")) == "near.png"
    assert scene_image_path(_A(near_path="", far_path="far.png", image_path="legacy.png")) == "far.png"
    assert scene_image_path(_A(near_path="", far_path="", image_path="legacy.png")) == "legacy.png"
    assert scene_image_path(_A(near_path="", far_path="", image_path="")) == ""


def test_build_shot_references_scene_uses_near_path():
    scene = _A(
        id="s1",
        kind="scene",
        name="青川渡",
        near_path="near.png",
        far_path="far.png",
        image_path="legacy.png",
        half_path="",
        full_path="",
    )
    slots = [{"index": 1, "kind": "scene", "asset_id": "s1", "image_key": "scene"}]
    refs = build_shot_references(scene=scene, lines=[], slots=slots, assets_by_id={"s1": scene})
    assert refs[0]["path"] == "near.png"
    assert refs[0]["uploaded"] is True


def test_build_shot_references_one_portrait_per_character():
    scene = _A(id="s1", kind="scene", name="青川渡", image_path="", half_path="", full_path="")
    char = _A(id="c1", kind="character", name="林砚之", image_path="", half_path="h.png", full_path="f.png")
    slots = [
        {"index": 1, "kind": "character", "asset_id": "c1", "image_key": "half", "position": "中"},
        {"index": 2, "kind": "scene", "asset_id": "s1", "image_key": "scene"},
    ]
    refs = build_shot_references(
        scene=scene,
        lines=[{"asset_id": "c1", "position": "中", "image_key": "half"}],
        slots=slots,
        props=[],
        assets_by_id={"s1": scene, "c1": char},
    )
    assert len([r for r in refs if r["mode"] == "image"]) == 2
    assert refs[0]["image_key"] == "half"
    assert refs[0]["uploaded"] is True


def test_text_fallback_prop_shown_without_fourth_image_slot():
    prop = _A(id="p1", kind="prop", name="半块玉佩", image_path="p.png", half_path="", full_path="")
    char = _A(id="c1", kind="character", name="林砚之", image_path="", half_path="h.png", full_path="f.png")
    refs = build_shot_references(
        scene=None,
        lines=[{"asset_id": "c1", "position": "中", "image_key": "full"}],
        slots=[{"index": 1, "kind": "character", "asset_id": "c1", "image_key": "full", "position": "中"}],
        props=[prop],
        assets_by_id={"c1": char, "p1": prop},
        text_fallbacks=[
            {
                "kind": "prop",
                "asset_id": "p1",
                "image_key": "prop",
                "name": "半块玉佩",
                "text": "刻着苏字的半块玉佩",
                "note": "文字描述补足",
            }
        ],
    )
    assert len([r for r in refs if r["mode"] == "image"]) == 1
    text_refs = [r for r in refs if r["mode"] == "text"]
    assert len(text_refs) == 1
    assert text_refs[0]["status_zh"] == "文字描述补足"
    assert "玉佩" in text_refs[0]["asset_name"]
