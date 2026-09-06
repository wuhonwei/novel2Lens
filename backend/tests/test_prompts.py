from app.domain.prompts import compile_first_frame, compile_h3
from app.domain.slots import SlotSubject, pack_qwen_slots


def test_first_frame_with_scene_uses_image_one_as_plate():
    # With 2 people, scene is text-fallback so both faces keep image slots.
    result = pack_qwen_slots(
        characters=[
            SlotSubject(asset_id="c1", kind="character", position="左一", facing="朝右", image_key="full", refer_as="少年"),
            SlotSubject(asset_id="c2", kind="character", position="右一", facing="朝左", image_key="full", refer_as="老者"),
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="青川渡口", desc_zh="雾渡"),
    )
    out = compile_first_frame(
        style="半写实、东方江湖、电影布光",
        slots=result.slots,
        character_count=2,
        actions={"左一": "神色苍白，双手递出玉佩", "右一": "接过玉佩，指尖颤抖"},
        text_fallbacks=result.text_fallbacks,
    )
    assert "场景「青川渡口」无参考图槽" in out.zh or "雾渡" in out.zh
    assert "图一是左一" in out.zh
    assert "图二是右一" in out.zh
    assert "恰好2人" in out.zh
    assert "互不相同" in out.zh or "不同面孔" in out.zh or "禁止复制同一张脸" in out.zh
    assert "半身或全身二选一" not in out.zh
    assert "林砚" not in out.zh


def test_first_frame_slot_includes_character_name_when_present():
    result = pack_qwen_slots(
        characters=[
            SlotSubject(
                asset_id="c1",
                kind="character",
                position="左一",
                facing="朝右",
                image_key="full",
                name="林砚之",
            ),
            SlotSubject(
                asset_id="c2",
                kind="character",
                position="右一",
                facing="朝左",
                image_key="full",
                name="陈守义",
            ),
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="青川渡"),
    )
    out = compile_first_frame(
        style="国漫3D",
        slots=result.slots,
        character_count=2,
        text_fallbacks=result.text_fallbacks,
    )
    assert "林砚之" in out.zh
    assert "陈守义" in out.zh
    assert "禁止复制同一张脸" in out.zh or "互不相同" in out.zh
    assert [s.kind for s in result.slots] == ["character", "character"]


def test_first_frame_half_only_does_not_mention_full_companion():
    result = pack_qwen_slots(
        characters=[SlotSubject(asset_id="c1", kind="character", position="中", facing="面向镜头", image_key="half")],
        scene=SlotSubject(asset_id="s1", kind="scene", name="渡口"),
    )
    out = compile_first_frame(
        style="半写实",
        slots=result.slots,
        character_count=1,
        actions={"中": "站立"},
        text_fallbacks=result.text_fallbacks,
    )
    assert "图一是中" in out.zh
    assert "半身即图一人物" in out.zh
    assert "图二为场景底板" in out.zh
    assert "仅用于锁定面部" not in out.zh
    assert "全身图为准" not in out.zh


def test_overflow_scene_and_prop_use_text_descriptions():
    result = pack_qwen_slots(
        characters=[
            SlotSubject(asset_id=f"c{i}", kind="character", position=p, image_key="full", name=f"人{i}")
            for i, p in enumerate(["左一", "中", "右一"], start=1)
        ],
        scene=SlotSubject(asset_id="s1", kind="scene", name="青川渡口", desc_zh="湿冷白雾中的青石渡口"),
        props=[SlotSubject(asset_id="p1", kind="prop", name="苏字玉佩", desc_zh="刻着苏字的半块玉佩")],
    )
    out = compile_first_frame(
        style="半写实",
        slots=result.slots,
        character_count=3,
        text_fallbacks=result.text_fallbacks,
    )
    assert "图四" not in out.zh
    assert "场景「青川渡口」无参考图槽" in out.zh
    assert "湿冷白雾中的青石渡口" in out.zh
    assert "核心物品「苏字玉佩」无参考图槽" in out.zh
    assert "刻着苏字的半块玉佩" in out.zh


def test_first_frame_without_scene_draws_background_from_text():
    result = pack_qwen_slots(
        characters=[SlotSubject(asset_id="c1", kind="character", position="中", facing="面向镜头", image_key="full", refer_as="少年")],
    )
    out = compile_first_frame(
        style="半写实",
        slots=result.slots,
        character_count=1,
        background="晨雾中的青石渡口，老槐树",
        text_fallbacks=result.text_fallbacks,
    )
    assert "绘制背景" in out.zh
    assert "图一是中" in out.zh
    assert "青石渡口" in out.zh


def test_h3_uses_image_tag_and_position_nouns_not_names():
    text = compile_h3(
        camera="固定",
        camera_detail="雾气微微流动",
        character_count=2,
        lines=[
            {
                "position": "左一",
                "refer_as": "少年",
                "facing": "朝右",
                "action": "递出玉佩",
                "voice_direction": "哽咽而轻",
                "dialogue": "我母亲叫苏晚卿",
            },
            {
                "position": "右一",
                "refer_as": "老者",
                "facing": "朝左",
                "action": "接过玉佩",
                "voice_direction": "",
                "dialogue": "",
            },
        ],
        narration="江雾更浓了。",
    )
    assert "<Image 1>" in text
    assert "左一的少年" in text
    assert "右一的老者" in text
    assert "始终为 2 人" in text
    assert "苏晚卿" in text
    assert "林砚之" not in text.replace("我母亲叫苏晚卿", "")
    assert "禁止新增人物" in text
