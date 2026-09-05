from app.domain.registry import (
    apply_registry_delta,
    is_registry_complete,
    merge_registry_entry,
    normalize_kind,
    registry_completeness,
)


def test_normalize_kind_maps_chinese_and_aliases():
    assert normalize_kind("人物") == "character"
    assert normalize_kind("角色") == "character"
    assert normalize_kind("场景") == "scene"
    assert normalize_kind("地点") == "scene"
    assert normalize_kind("物品") == "prop"
    assert normalize_kind("道具") == "prop"
    assert normalize_kind("character") == "character"
    assert normalize_kind("unknown") == "prop"


def test_merge_registry_supplements_missing_fields_without_duplicating():
    existing = {
        "kind": "character",
        "name": "林砚之",
        "aliases": ["砚之"],
        "refer_as": "少年",
        "desc_zh": "清俊少年",
        "appearance": {"body": "清瘦"},
    }
    incoming = {
        "kind": "character",
        "name": "林砚之",
        "aliases": ["小砚"],
        "refer_as": "少年",
        "desc_zh": "十七岁，洗白长衫",
        "appearance": {"face": "眉眼清俊", "clothing": "发白长衫"},
        "age_band": "十七岁",
    }
    merged = merge_registry_entry(existing, incoming)
    assert set(merged["aliases"]) == {"砚之", "小砚"}
    assert "洗白长衫" in merged["desc_zh"]
    assert merged["appearance"]["face"] == "眉眼清俊"
    assert merged["appearance"]["clothing"] == "发白长衫"
    assert merged["appearance"]["body"] == "清瘦"
    assert merged["age_band"] == "十七岁"


def test_completeness_requires_description_for_each_kind():
    assets = [
        {"kind": "character", "name": "林砚之", "desc_zh": "", "appearance": {}, "background_zh": "青川渡遗孤"},
        {"kind": "scene", "name": "青川渡口", "desc_zh": "雾中渡口"},
        {"kind": "prop", "name": "玉佩", "desc_zh": "苏字玉佩"},
    ]
    report = registry_completeness(assets)
    assert report["complete"] is False
    assert any(i["name"] == "林砚之" for i in report["incomplete"])
    assets[0]["desc_zh"] = "苍白少年，发白长衫"
    assert is_registry_complete(assets)


def test_character_background_and_look_stay_split():
    from app.domain.registry import apply_registry_delta, look_text, merge_registry_entry

    base: list[dict] = []
    apply_registry_delta(
        base,
        [
            {
                "kind": "character",
                "name": "林砚之",
                "background": "青川渡遗孤，寻母苏晚卿",
                "look_zh": "眉眼清俊，洗白长衫",
                "appearance": {"face": "眉眼清俊", "clothing": "发白长衫"},
                "refer_as": "少年",
            }
        ],
    )
    assert base[0]["background_zh"] == "青川渡遗孤，寻母苏晚卿"
    assert "遗孤" not in base[0]["desc_zh"]
    assert "眉眼清俊" in base[0]["desc_zh"]
    assert "遗孤" not in look_text(base[0])
    assert "眉眼清俊" in look_text(base[0])

    merged = merge_registry_entry(
        base[0],
        {"kind": "character", "name": "林砚之", "background": "陈伯旧友之子", "look_zh": "清瘦"},
    )
    assert "寻母" in merged["background_zh"]
    assert "旧友" in merged["background_zh"]
    assert "清瘦" in merged["desc_zh"]
    assert "旧友" not in merged["desc_zh"]


def test_apply_registry_delta_creates_and_supplements():
    base: list[dict] = []
    created, updated = apply_registry_delta(
        base,
        [
            {"kind": "人物", "name": "陈守义", "aliases": ["陈伯"], "notes": "老船工"},
            {"kind": "scene", "name": "茅草屋", "desc_zh": "渡口茅屋"},
        ],
    )
    assert len(base) == 2
    assert created == 2
    assert base[0]["kind"] == "character"
    assert "老船工" in base[0]["desc_zh"]
    _, updated2 = apply_registry_delta(
        base,
        [{"kind": "character", "name": "陈守义", "desc_zh": "花白头发，藏青短打", "appearance": {"hair": "花白"}}],
    )
    assert updated2 == 1
    assert "藏青短打" in base[0]["desc_zh"]
    assert base[0]["appearance"]["hair"] == "花白"


def test_pass1_chinese_keys_force_character_kind():
    from app.services import _pass1_rows

    rows = _pass1_rows(
        {
            "人物": [{"name": "林砚之", "kind": "prop", "notes": "少年"}],
            "场景": [{"name": "渡口"}],
            "物品": [{"name": "玉佩"}],
        }
    )
    by_name = {r["name"]: r["kind"] for r in rows}
    assert by_name["林砚之"] == "character"
    assert by_name["渡口"] == "scene"
    assert by_name["玉佩"] == "prop"


def test_sanitize_look_drops_emotion_action_and_occupation():
    from app.domain.registry import sanitize_look_text, sanitize_appearance

    text = sanitize_look_text(
        "十七岁清瘦，眉眼清俊，洗白长衫，眼神从迷茫转为坚定，动作沉稳，笑靥如花，老船工"
    )
    assert "眉眼清俊" in text
    assert "洗白长衫" in text
    assert "迷茫" not in text
    assert "沉稳" not in text
    assert "笑靥如花" not in text
    assert "老船工" not in text

    app = sanitize_appearance(
        {"eyes": "眼神坚定", "face": "眉眼清俊", "clothing": "藏青短打"}
    )
    assert "face" in app
    assert "clothing" in app
    assert "eyes" not in app or "坚定" not in app.get("eyes", "")
    from app.domain.registry import sanitize_aliases, sanitize_character_fields, apply_registry_delta

    cleaned = sanitize_aliases(
        ["砚之", "少年", "母亲", "陈伯", "人"],
        name="林砚之",
        refer_as="少年",
    )
    assert cleaned == ["砚之", "陈伯"]

    row = sanitize_character_fields(
        {
            "name": "林砚之",
            "aliases": ["少年", "母亲", "砚之"],
            "refer_as": "",
        }
    )
    assert row["aliases"] == ["砚之"]
    assert row["refer_as"] == "少年"

    assets: list[dict] = []
    apply_registry_delta(
        assets,
        [
            {
                "kind": "character",
                "name": "林砚之",
                "aliases": ["少年", "母亲", "砚之"],
                "refer_as": "少年",
                "notes": "清俊",
            },
            {"kind": "character", "name": "母亲", "aliases": [], "notes": "亡母"},
        ],
    )
    assert len(assets) == 1
    assert assets[0]["name"] == "林砚之"
    assert "少年" not in assets[0]["aliases"]
    assert "母亲" not in assets[0]["aliases"]
    assert "砚之" in assets[0]["aliases"]
