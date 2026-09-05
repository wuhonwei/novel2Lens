from app.domain.prompts import compile_first_frame, compile_h3
from app.domain.slots import pack_qwen_slots, SlotSubject


def test_first_frame_with_scene_uses_image_one_as_plate():
    slots = pack_qwen_slots(
        has_scene=True,
        characters=[
            SlotSubject(asset_id="c1", position="左一", facing="朝右", image_key="full", refer_as="少年"),
            SlotSubject(asset_id="c2", position="右一", facing="朝左", image_key="full", refer_as="老者"),
        ],
    )
    out = compile_first_frame(
        style="半写实、东方江湖、电影布光",
        slots=slots,
        character_count=2,
        actions={"左一": "神色苍白，双手递出玉佩", "右一": "接过玉佩，指尖颤抖"},
    )
    assert "图一为场景底板" in out.zh
    assert "图二是左一" in out.zh
    assert "图三是右一" in out.zh
    assert "恰好2人" in out.zh
    assert "半身或全身二选一" in out.zh
    assert "image 1 as the environment plate" in out.en.lower()
    assert "image 2 is the leftmost" in out.en.lower()
    assert "林砚" not in out.zh


def test_first_frame_half_only_does_not_mention_full_companion():
    slots = pack_qwen_slots(
        has_scene=True,
        characters=[SlotSubject(asset_id="c1", position="中", facing="面向镜头", image_key="half")],
    )
    out = compile_first_frame(style="半写实", slots=slots, character_count=1, actions={"中": "站立"})
    assert "图二是中" in out.zh
    assert "半身即图二人物" in out.zh
    assert "图三" not in out.zh
    assert "仅用于锁定面部" not in out.zh
    assert "全身图为准" not in out.zh


def test_first_frame_without_scene_draws_background_from_text():
    slots = pack_qwen_slots(
        has_scene=False,
        characters=[SlotSubject(asset_id="c1", position="中", facing="面向镜头", image_key="full", refer_as="少年")],
    )
    out = compile_first_frame(
        style="半写实",
        slots=slots,
        character_count=1,
        background="晨雾中的青石渡口，老槐树",
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
    assert "苏晚卿" in text  # dialogue may quote source names in speech
    assert "林砚之" not in text.replace("我母亲叫苏晚卿", "")
    assert "禁止新增人物" in text
