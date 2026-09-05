from app.image_gen import _style_for


def test_guoman_3d_maps_to_guofeng():
    assert _style_for("character", "国漫3D") == "guofeng_cg"
    assert _style_for("scene", "国漫3D") == "guofeng"
    assert _style_for("prop", "国漫3D") == "guofeng"


def test_half_prompt_mentions_look_and_outfit():
    from types import SimpleNamespace
    from app.image_gen import build_field_prompt

    project = SimpleNamespace(style="国漫3D")
    asset = SimpleNamespace(
        kind="character",
        name="林砚之",
        refer_as="少年",
        age_band="十七岁",
        desc_zh="清俊少年，洗白长衫",
        appearance_json="{}",
        aliases_json="[]",
    )
    text = build_field_prompt(project, asset, "half")
    assert "半身" in text or "胸像" in text
    assert "洗白长衫" in text or "长衫" in text
    assert "服饰" in text
