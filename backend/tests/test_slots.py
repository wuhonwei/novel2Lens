from app.domain.slots import max_named_characters, pack_qwen_slots, SlotSubject


def test_named_cap_shrinks_when_scene_present():
    assert max_named_characters(has_scene=True) == 2
    assert max_named_characters(has_scene=False) == 3


def test_scene_plus_two_people_fills_three_slots():
    slots = pack_qwen_slots(
        has_scene=True,
        characters=[
            SlotSubject(asset_id="c1", position="左一", image_key="full"),
            SlotSubject(asset_id="c2", position="右一", image_key="full"),
        ],
    )
    kinds = [s.kind for s in slots]
    assert kinds == ["scene", "character", "character"]
    assert slots[1].position == "左一"
    assert slots[2].position == "右一"


def test_single_person_scene_can_lock_face_with_half_body():
    slots = pack_qwen_slots(
        has_scene=True,
        characters=[SlotSubject(asset_id="c1", position="中", image_key="full")],
        half_lock=True,
    )
    assert [s.kind for s in slots] == ["scene", "character", "character"]
    assert slots[1].image_key == "full"
    assert slots[2].image_key == "half"


def test_no_scene_three_people():
    chars = [
        SlotSubject(asset_id=f"c{i}", position=p, image_key="full")
        for i, p in enumerate(["左一", "中", "右一"], start=1)
    ]
    slots = pack_qwen_slots(has_scene=False, characters=chars)
    assert len(slots) == 3
    assert all(s.kind == "character" for s in slots)


def test_prop_only_fills_empty_slot_without_scene_and_at_most_two_people():
    slots = pack_qwen_slots(
        has_scene=False,
        characters=[SlotSubject(asset_id="c1", position="中", image_key="full")],
        prop=SlotSubject(asset_id="p1", image_key="prop"),
    )
    assert any(s.kind == "prop" for s in slots)


def test_rejects_three_named_people_when_scene_present():
    chars = [
        SlotSubject(asset_id=f"c{i}", position=p, image_key="full")
        for i, p in enumerate(["左一", "中", "右一"], start=1)
    ]
    try:
        pack_qwen_slots(has_scene=True, characters=chars)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "2" in str(exc)
