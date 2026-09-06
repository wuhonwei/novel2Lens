# -*- coding: utf-8 -*-
from types import SimpleNamespace

from app.image_gen import _PROP_SHAPE_HINTS, _prop_visual_brief, build_field_prompt


def test_prop_visual_brief_drops_plot_narrative():
    raw = "陈守义的船，是他的念想，被赵万山的人砸坏后，镇上的人帮忙修好。"
    out = _prop_visual_brief("乌木船", raw)
    assert "念想" not in out
    assert "赵万山" not in out
    assert "砸坏" not in out
    assert "修好" not in out
    assert "陈守义" not in out
    # Falls back to the prop name when nothing visual remains.
    assert out == "乌木船"


def test_prop_visual_brief_keeps_physical_cues():
    out = _prop_visual_brief("玉佩", "半块碧玉雕花玉佩，边缘有裂纹，可对半相合")
    assert "碧玉" in out
    assert "裂纹" in out


def test_wumuchuan_prompt_uses_shape_not_plot():
    project = SimpleNamespace(style="国漫3D")
    asset = SimpleNamespace(
        kind="prop",
        name="乌木船",
        desc_zh="陈守义的船，是他的念想，被赵万山的人砸坏后，镇上的人帮忙修好。",
        appearance_json="{}",
        aliases_json="[]",
        refer_as="",
        age_band="",
    )
    text = build_field_prompt(project, asset, "image")
    assert "念想" not in text
    assert "赵万山" not in text
    assert "陈守义" not in text
    assert "乌木" in text or "船" in _PROP_SHAPE_HINTS["乌木船"]
    assert "乌木船" in _PROP_SHAPE_HINTS
    assert _PROP_SHAPE_HINTS["乌木船"] in text
