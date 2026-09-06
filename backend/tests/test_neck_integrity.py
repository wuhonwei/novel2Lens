# -*- coding: utf-8 -*-
"""Neck void / black-collar artifacts must be discouraged in character prompts."""
from types import SimpleNamespace

from app.comfy_pipeline.character_prompt import enrich_character_negative, enrich_character_prompt
from app.db import Asset, Project
from app.image_gen import build_field_prompt


def test_fullbody_prompt_locks_neck_integrity():
    project = Project(id="p", title="t", style="国漫3D", source_text="x")
    asset = Asset(
        id="a",
        project_id="p",
        kind="character",
        name="苏婆婆",
        refer_as="老婆婆",
        age_band="六十岁",
        desc_zh="白发苍苍，粗布衣衫",
        appearance_json='{"clothing": "粗布衣衫"}',
    )
    text = build_field_prompt(project, asset, "full")
    assert "脖子" in text or "领口" in text
    assert "黑洞" in text or "高领" in text


def test_enrich_adds_neck_void_negatives():
    neg = enrich_character_negative(
        "全身站立人像，粗布衣衫",
        "blurry",
        style="guofeng_cg",
        no_background=True,
        gender="female",
        age_tier="elder",
    )
    low = neg.lower()
    assert "neck" in low or "throat" in low
    assert "black turtleneck" in low or "void" in low or "hole" in low


def test_enrich_positive_mentions_visible_neck_skin():
    pos = enrich_character_prompt(
        "全身站立人像，粗布衣衫，白发",
        "guofeng_cg",
        no_background=True,
        gender="female",
        age_tier="elder",
    )
    low = pos.lower()
    assert "neck" in low
    assert "collar" in low or "领口" in pos
