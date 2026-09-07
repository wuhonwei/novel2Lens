from app.domain.registry import (
    character_look_trinity_missing,
    ensure_character_look_trinity,
    look_text,
    registry_completeness,
    sanitize_character_fields,
)


def test_ensure_trinity_prefixes_gender_age_body():
    desc, app, age = ensure_character_look_trinity(
        name="赵万山随从",
        refer_as="打手",
        age_band="青年",
        desc_zh="面容粗犷，身穿深色短打",
        appearance={"body": "魁梧壮硕", "clothing": "深色短打"},
    )
    assert desc.startswith("性别：")
    assert "年龄段：青年" in desc
    assert "身材：魁梧壮硕" in desc
    assert app["gender"] in {"男", "女", "不明"}
    assert app["body"] == "魁梧壮硕"
    assert age == "青年"
    assert "性别：" in look_text(
        {
            "name": "赵万山随从",
            "refer_as": "打手",
            "age_band": "青年",
            "desc_zh": desc,
            "appearance": app,
        }
    )


def test_sanitize_character_fields_stamps_trinity():
    row = sanitize_character_fields(
        {
            "name": "林砚之",
            "refer_as": "少年",
            "age_band": "17岁",
            "look_zh": "清瘦，洗白长衫",
            "appearance": {"face": "清俊", "clothing": "洗白长衫"},
        }
    )
    assert row["appearance"]["gender"] == "男"
    assert row["appearance"]["body"]
    assert "性别：男" in row["look_zh"]
    assert "年龄段：17岁" in row["look_zh"]
    assert "身材：" in row["look_zh"]


def test_completeness_flags_missing_trinity_on_raw_asset():
    out = registry_completeness(
        [
            {
                "kind": "character",
                "name": "路人甲",
                "desc_zh": "穿灰衣",
                "appearance": {},
                "age_band": "",
            }
        ]
    )
    assert out["complete"] is False
    assert any("必带项" in (x.get("reason") or "") for x in out["incomplete"])


def test_trinity_missing_helper():
    assert "性别" in character_look_trinity_missing(
        {"desc_zh": "清瘦", "appearance": {"body": "清瘦"}, "age_band": "青年"}
    )
    assert character_look_trinity_missing(
        {
            "desc_zh": "性别：男，年龄段：青年，身材：清瘦",
            "appearance": {"gender": "男", "body": "清瘦"},
            "age_band": "青年",
        }
    ) == []
