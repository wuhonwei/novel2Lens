# -*- coding: utf-8 -*-
"""Black-outfit hard-lock must not fire on hair color alone."""
from app.comfy_pipeline.character_prompt import prompt_requests_black_outfit


def test_black_long_hair_is_not_black_outfit():
    prompt = (
        "角色名：苏晚卿。穿着旗袍，年轻时很美丽，鹅蛋脸，薄唇，黑色长发，整齐，白皙。"
    )
    assert prompt_requests_black_outfit(prompt) is False


def test_black_hair_variants_are_not_outfit():
    for hair in ("黑发", "黑色短发", "黑色头发", "黑直发", "黑色卷发"):
        assert prompt_requests_black_outfit(f"女子，{hair}，穿旗袍") is False


def test_heiyi_assassin_still_requests_black_outfit():
    assert prompt_requests_black_outfit("黑衣人，黑衣蒙面，眼神阴冷") is True
    assert prompt_requests_black_outfit("身穿黑色长衫，戴帽遮脸") is True
    assert prompt_requests_black_outfit("一袭黑袍，夜行") is True
