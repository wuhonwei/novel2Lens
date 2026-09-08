from app.domain.slots import (
    MAX_NAMED_CHARACTERS,
    PackResult,
    SlotSubject,
    max_named_characters,
    pack_qwen_slots,
)


def test_named_cap_is_soft_unlimited():
    assert max_named_characters() >= 99
    assert MAX_NAMED_CHARACTERS >= 99


def test_priority_scene_then_characters_then_prop():
    result = pack_qwen_slots(
        characters=[
            SlotSubject(asset_id="c1", kind="character", position="左一", image_key="full", name="林砚之"),
            SlotSubject(asset_id="c2", kind="character", position="右一", image_key="full", name="陈守义"),
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="青川渡口", desc_zh="雾中青石渡口"),
        props=[SlotSubject(asset_id="p1", kind="prop", name="玉佩", desc_zh="半块玉佩")],
    )
    assert isinstance(result, PackResult)
    assert [s.kind for s in result.slots] == ["scene", "character", "character", "prop"]
    assert result.text_fallbacks == []


def test_three_characters_keep_scene_and_prop_as_slots():
    result = pack_qwen_slots(
        characters=[
            SlotSubject(asset_id=f"c{i}", kind="character", position=p, image_key="full")
            for i, p in enumerate(["左一", "中", "右一"], start=1)
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="渡口", desc_zh="雾渡"),
        props=[SlotSubject(asset_id="p1", kind="prop", name="玉佩", desc_zh="半块玉佩")],
    )
    assert [s.kind for s in result.slots] == [
        "scene",
        "character",
        "character",
        "character",
        "prop",
    ]
    assert result.text_fallbacks == []


def test_four_characters_all_get_image_slots_with_scene():
    result = pack_qwen_slots(
        characters=[
            SlotSubject(asset_id=f"c{i}", kind="character", position="中", image_key="full")
            for i in range(1, 5)
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="渡口", desc_zh="雾渡"),
    )
    assert len(result.slots) == 5
    assert result.slots[0].kind == "scene"
    assert all(s.kind == "character" for s in result.slots[1:])


def test_single_person_uses_only_one_portrait_never_both():
    result = pack_qwen_slots(
        characters=[SlotSubject(asset_id="c1", kind="character", position="中", image_key="half")],
        scene=SlotSubject(asset_id="s1", kind="scene", name="渡口"),
        half_lock=True,
    )
    assert [s.kind for s in result.slots] == ["scene", "character"]
    assert result.slots[1].image_key == "half"


def test_duplicate_character_subjects_collapse_to_one_slot():
    result = pack_qwen_slots(
        characters=[
            SlotSubject(asset_id="c1", kind="character", position="中", image_key="full"),
            SlotSubject(asset_id="c1", kind="character", position="中", image_key="half"),
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="渡口"),
    )
    assert [s.kind for s in result.slots] == ["scene", "character"]
    assert result.slots[1].image_key == "full"


def test_allows_nine_named_people():
    chars = [
        SlotSubject(asset_id=f"c{i}", kind="character", position="中", image_key="full")
        for i in range(1, 10)
    ]
    result = pack_qwen_slots(characters=chars)
    assert len(result.slots) == 9
    assert all(s.kind == "character" for s in result.slots)
