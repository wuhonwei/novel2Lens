# -*- coding: utf-8 -*-
from app.domain.dialogue import extract_dialogue_quotes, salvage_dialogue


def test_extract_dialogue_quotes_skips_seal_words():
    text = '信上只有一行字：“去青川渡，找陈守义，他会护你。”玉佩上刻着“忠守”。'
    quotes = extract_dialogue_quotes(text)
    assert "去青川渡，找陈守义，他会护你。" in quotes
    assert "忠守" not in quotes


def test_salvage_assigns_quote_to_named_speaker():
    lines = [
        {
            "name": "林砚之",
            "position": "中",
            "dialogue": "",
            "voice_direction": "",
        }
    ]
    excerpt = "“请问，是陈守义老伯吗？” 林砚之轻声开口，声音在雾里散开。"
    out, nar = salvage_dialogue(lines, source_excerpt=excerpt, narration="")
    assert out[0]["dialogue"] == "请问，是陈守义老伯吗？"
    assert out[0]["voice_direction"] in ("", "轻声")
    assert nar == ""


def test_salvage_puts_unregistered_speaker_into_narration():
    lines = [
        {
            "name": "林砚之",
            "position": "中",
            "dialogue": "",
            "voice_direction": "",
        }
    ]
    excerpt = '茶馆里的老板娘给他添了碗热茶，指了指雾深处，“这会儿天没亮透，他应该在收拾船，你去渡口边找，准能找着。”'
    out, nar = salvage_dialogue(lines, source_excerpt=excerpt, narration="")
    assert out[0]["dialogue"] == ""
    assert "这会儿天没亮透" in nar
    assert "画外口播" in nar


def test_salvage_empty_cast_uses_narration():
    lines: list[dict] = []
    excerpt = "“赵万山，你身为商人，不思诚信经营，反而欺压百姓，强占民地，目无王法！”"
    out, nar = salvage_dialogue(lines, source_excerpt=excerpt, narration="")
    assert out == []
    assert "赵万山，你身为商人" in nar


def test_salvage_does_not_overwrite_existing_dialogue():
    lines = [{"name": "林砚之", "dialogue": "已有台词", "voice_direction": ""}]
    excerpt = "“请问，是陈守义老伯吗？” 林砚之轻声开口。"
    out, nar = salvage_dialogue(lines, source_excerpt=excerpt, narration="")
    assert out[0]["dialogue"] == "已有台词"
    assert nar == ""


def test_salvage_letter_line_becomes_character_reading():
    lines = [{"name": "林砚之", "dialogue": "", "voice_direction": ""}]
    excerpt = '信上只有一行字：“去青川渡，找陈守义，他会护你。”'
    out, nar = salvage_dialogue(lines, source_excerpt=excerpt, narration="")
    assert "去青川渡" in out[0]["dialogue"]
    assert out[0]["voice_direction"] in ("读信", "轻声")


def test_compile_shot_prompts_salvages_dialogue_into_h3():
    from app.db import Asset, Project, Shot
    from app.storyboard_ops import compile_shot_prompts

    project = Project(id="p", title="t", style="国风3D", source_text="x")
    char = Asset(
        id="c1",
        project_id="p",
        kind="character",
        name="林砚之",
        refer_as="少年",
        full_path="f.png",
        half_path="h.png",
    )
    scene = Asset(
        id="s1",
        project_id="p",
        kind="scene",
        name="青川渡",
        far_path="far.png",
        image_path="far.png",
    )
    shot = Shot(
        id="sh1",
        project_id="p",
        chapter_id="ch1",
        order_index=1,
        scene_asset_id="s1",
        character_count=1,
        camera="固定",
        source_excerpt="“请问，是陈守义老伯吗？” 林砚之轻声开口。",
        lines_json='[{"asset_id":"c1","name":"林砚之","position":"中","facing":"面向镜头","image_key":"full","portrait":"full","action":"","dialogue":"","voice_direction":""}]',
    )
    compile_shot_prompts(project, shot, [char, scene])
    assert "请问，是陈守义老伯吗" in (shot.h3_prompt or "")
    assert "说道" in (shot.h3_prompt or "")
    assert "无人声" not in (shot.h3_prompt or "")
