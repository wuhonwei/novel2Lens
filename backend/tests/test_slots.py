from app.domain.slots import (
    MAX_NAMED_CHARACTERS,
    PackResult,
    SlotSubject,
    max_named_characters,
    pack_qwen_slots,
)


def test_named_cap_is_three_with_or_without_scene():
    assert max_named_characters(has_scene=True) == 3
    assert max_named_characters(has_scene=False) == 3
    assert MAX_NAMED_CHARACTERS == 3


def test_priority_characters_then_scene_then_prop():
    result = pack_qwen_slots(
        characters=[
            SlotSubject(asset_id="c1", kind="character", position="左一", image_key="full", name="林砚之"),
            SlotSubject(asset_id="c2", kind="character", position="右一", image_key="full", name="陈守义"),
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="青川渡口", desc_zh="雾中青石渡口"),
        props=[SlotSubject(asset_id="p1", kind="prop", name="玉佩", desc_zh="半块玉佩")],
    )
    assert isinstance(result, PackResult)
    # Dual-character shots reserve image slots for faces; scene+prop become text.
    assert [s.kind for s in result.slots] == ["character", "character"]
    assert len(result.slots) == 2
    fb_kinds = [f.kind for f in result.text_fallbacks]
    assert "scene" in fb_kinds and "prop" in fb_kinds
    assert "青川渡口" in next(f.name for f in result.text_fallbacks if f.kind == "scene")
    assert "玉佩" in next(f.name for f in result.text_fallbacks if f.kind == "prop")


def test_three_characters_push_scene_to_text():
    result = pack_qwen_slots(
        characters=[
            SlotSubject(asset_id=f"c{i}", kind="character", position=p, image_key="full")
            for i, p in enumerate(["左一", "中", "右一"], start=1)
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="渡口", desc_zh="雾渡"),
        props=[SlotSubject(asset_id="p1", kind="prop", name="玉佩", desc_zh="半块玉佩")],
    )
    assert [s.kind for s in result.slots] == ["character", "character", "character"]
    kinds = [f.kind for f in result.text_fallbacks]
    assert kinds == ["scene", "prop"]


def test_single_person_uses_only_one_portrait_never_both():
    result = pack_qwen_slots(
        characters=[SlotSubject(asset_id="c1", kind="character", position="中", image_key="half")],
        scene=SlotSubject(asset_id="s1", kind="scene", name="渡口"),
        half_lock=True,
    )
    assert [s.kind for s in result.slots] == ["character", "scene"]
    assert result.slots[0].image_key == "half"


def test_duplicate_character_subjects_collapse_to_one_slot():
    result = pack_qwen_slots(
        characters=[
            SlotSubject(asset_id="c1", kind="character", position="中", image_key="full"),
            SlotSubject(asset_id="c1", kind="character", position="中", image_key="half"),
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="渡口"),
    )
    assert [s.kind for s in result.slots] == ["character", "scene"]
    assert result.slots[0].image_key == "full"


def test_rejects_four_named_people():
    chars = [
        SlotSubject(asset_id=f"c{i}", kind="character", position="中", image_key="full")
        for i in range(1, 5)
    ]
    try:
        pack_qwen_slots(characters=chars)
    except ValueError as exc:
        assert "3" in str(exc)
        return
    raise AssertionError("expected ValueError")
