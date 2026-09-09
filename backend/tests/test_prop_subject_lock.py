# -*- coding: utf-8 -*-
"""Prop T2I must keep the named object as subject — not related props/plot props."""
from types import SimpleNamespace

from app.domain.prop_hints import lookup_prop_shape_zh, scrub_prop_desc
from app.image_gen import build_field_prompt


def _prop(name: str, desc: str):
    project = SimpleNamespace(style="国漫3D")
    asset = SimpleNamespace(
        kind="prop",
        name=name,
        desc_zh=desc,
        appearance_json="{}",
        aliases_json="[]",
        refer_as="",
        age_band="",
    )
    return build_field_prompt(project, asset, "image")


def test_rosewood_box_not_swallowed_by_jade_lock_cue():
    text = _prop("紫檀木箱", "藏于山洞石室，锁孔形状与玉佩一致。")
    assert "紫檀木箱" in text or "木箱" in text
    assert "木箱" in lookup_prop_shape_zh("紫檀木箱") or "紫檀" in lookup_prop_shape_zh("紫檀木箱")
    assert "主体只能是" in text and "紫檀木箱" in text
    assert "禁止" in text and ("玉佩" in text or "挂件" in text)
    # Desc may mention lock shape, but must not invite a pendant hero shot.
    assert "核心道具特写：紫檀木箱" in text


def test_yellowed_photo_stays_flat_photo_not_jade_sphere():
    text = _prop("泛黄照片", "茅草屋桌上相框内，苏晚卿年轻时的旗袍照。")
    assert "照片" in lookup_prop_shape_zh("泛黄照片") or "相框" in lookup_prop_shape_zh("泛黄照片")
    assert "相框" in text or "照片" in text
    assert "平面" in text or "纸面" in text
    assert "花鸟" in text or "花卉" in text  # negatives
    scrubbed = scrub_prop_desc("泛黄照片", "茅草屋桌上相框内，苏晚卿年轻时的旗袍照。")
    assert "茅草屋" not in scrubbed


def test_suicide_letter_not_replaced_by_container_box():
    text = _prop(
        "母亲绝笔信",
        "泛黄的宣纸，字迹工整秀丽，墨色略淡，纸张边缘有轻微烧焦痕迹或磨损，折叠整齐，装在紫檀木盒中。",
    )
    assert "单页" in text or "平铺" in text
    assert "卷轴" in text  # banned
    assert "木杆" in text or "红绳" in text
    scrubbed = scrub_prop_desc(
        "母亲绝笔信",
        "泛黄的宣纸，字迹工整秀丽，装在紫檀木盒中。",
    )
    assert "紫檀木盒" not in scrubbed
    assert "宣纸" in scrubbed


def test_mountain_map_not_bonsai_landscape():
    text = _prop(
        "云栖山地图",
        "泛黄的绢布或厚纸，手绘山川河流线条，标注有“云栖山”字样及一个隐蔽山洞的标记，线条古朴，有岁月痕迹。",
    )
    assert "地图" in lookup_prop_shape_zh("云栖山地图")
    assert "地图" in text
    assert "盆景" in text or "风景" in text  # appear in negatives
    assert "禁止" in text
    assert "平面" in text or "展开" in text
