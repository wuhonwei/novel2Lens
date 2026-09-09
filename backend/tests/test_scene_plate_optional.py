# -*- coding: utf-8 -*-
from app.db import Asset, Project, Shot
from app.domain.slots import SlotSubject
from app.image_gen import build_field_prompt
from app.storyboard_ops import _prefer_scene_image_slot, _shot_unready, compile_shot_prompts


def test_scene_near_prompt_avoids_character_name_leak():
    project = Project(id="p", title="t", style="国漫3D", source_text="x")
    scene = Asset(
        id="s1",
        project_id="p",
        kind="scene",
        name="苏婆婆木屋",
        desc_zh="深山深处，篱笆，草药田，温馨简陋。",
    )
    near = build_field_prompt(project, scene, "near")
    far = build_field_prompt(project, scene, "far")
    assert "苏婆婆" not in near
    assert "苏婆婆" not in far
    assert "禁止" in near and ("任何人" in near or "人脸" in near)
    assert "禁止出现任何人" in far
    assert "草药田" in near or "篱笆" in near
    assert "草药田" in far or "篱笆" in far


def test_prefer_scene_plate_skips_all_half_closeups():
    half = SlotSubject(asset_id="c1", kind="character", image_key="half", name="陈守义")
    full = SlotSubject(asset_id="c1", kind="character", image_key="full", name="陈守义")
    assert _prefer_scene_image_slot([half]) is False
    assert _prefer_scene_image_slot([half, half]) is False
    assert _prefer_scene_image_slot([full]) is True
    assert _prefer_scene_image_slot([]) is True


def test_shot_unready_needs_at_least_one_ref():
    project = Project(id="p", title="t", style="国漫3D", source_text="x")
    char = Asset(id="c1", project_id="p", kind="character", name="陈守义", half_path="h.png")
    assert _shot_unready(project, []) is True
    assert _shot_unready(project, [(char, "half")]) is False
    bare = Project(id="p2", title="t", style="", source_text="x")
    assert _shot_unready(bare, [(char, "half")]) is True


def test_compile_omits_scene_plate_for_half_closeup():
    project = Project(id="p", title="t", style="国漫3D", source_text="x")
    scene = Asset(
        id="s1",
        project_id="p",
        kind="scene",
        name="苏婆婆木屋",
        desc_zh="深山篱笆草药田",
        near_path="projects/p/assets/s1/near.png",
        far_path="projects/p/assets/s1/far.png",
    )
    char = Asset(
        id="c1",
        project_id="p",
        kind="character",
        name="陈守义",
        half_path="projects/p/assets/c1/half.png",
        full_path="projects/p/assets/c1/full.png",
    )
    prop = Asset(
        id="pr1",
        project_id="p",
        kind="prop",
        name="遗物玉佩",
        image_path="projects/p/assets/pr1/image.png",
        desc_zh="旧玉佩",
    )
    shot = Shot(
        id="sh1",
        project_id="p",
        chapter_id="ch1",
        order_index=4,
        scene_asset_id=scene.id,
        prop_asset_ids_json='["pr1"]',
        lines_json='[{"asset_id":"c1","name":"陈守义","position":"中","facing":"面向镜头","portrait":"half","image_key":"half"}]',
        camera="微仰",
        action="低头看玉佩",
        background="",
        narration="",
        prompt_zh="",
    )
    compile_shot_prompts(project, shot, [scene, char, prop])
    import json

    slots = json.loads(shot.slots_json)
    kinds = [s["kind"] for s in slots]
    assert "scene" not in kinds
    assert "character" in kinds
    assert "prop" in kinds
    assert shot.first_frame_unready is False
    fbs = json.loads(shot.text_fallbacks_json)
    assert any(fb.get("kind") == "scene" for fb in fbs)
