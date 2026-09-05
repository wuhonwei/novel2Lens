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
        {"kind": "character", "name": "林砚之", "desc_zh": "", "appearance": {}},
        {"kind": "scene", "name": "青川渡口", "desc_zh": "雾中渡口"},
        {"kind": "prop", "name": "玉佩", "desc_zh": "苏字玉佩"},
    ]
    report = registry_completeness(assets)
    assert report["complete"] is False
    assert any(i["name"] == "林砚之" for i in report["incomplete"])
    assets[0]["desc_zh"] = "苍白少年，发白长衫"
    assert is_registry_complete(assets)


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
