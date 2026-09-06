from app.comfy_pipeline.persona import (
    identity_lock_zh,
    identity_negative,
    infer_age_tier,
    infer_gender,
)
from app.db import Asset, Project
from app.image_gen import build_field_prompt
from app.comfy_pipeline.character_prompt import enrich_character_prompt


def test_infer_male_from_refer_as():
    assert infer_gender(name="林砚之", refer_as="少年", age_band="17岁", look="清瘦少年") == "male"


def test_infer_elder_female_from_婆婆():
    assert infer_gender(name="苏婆婆", refer_as="老人", age_band="60岁左右", look="") == "female"
    assert infer_age_tier(name="苏婆婆", refer_as="老人", age_band="60岁左右", look="") == "elder"


def test_build_field_prompt_locks_male_and_elder():
    project = Project(id="p", title="t", style="国风3D、东方江湖", source_text="x")
    male = Asset(
        id="a1",
        project_id="p",
        kind="character",
        name="林砚之",
        refer_as="少年",
        age_band="17岁",
        desc_zh="清瘦少年，洗白长衫",
    )
    grandma = Asset(
        id="a2",
        project_id="p",
        kind="character",
        name="苏婆婆",
        refer_as="老人",
        age_band="60岁左右",
        desc_zh="花白头发，布衣",
    )
    m = build_field_prompt(project, male, "full")
    assert "男性" in m or "男子" in m
    assert "国风" in m or "古装" in m or "汉服" in m
    assert "不要现代衬衫" in m
    assert "角色名" not in m
    assert "林砚之" not in m
    g = build_field_prompt(project, grandma, "full")
    assert "老年" in g or "苍老" in g
    assert "不可年轻化" in g or "皱纹" in g
    assert "角色名" not in g
    assert "苏婆婆" not in g


def test_male_guofeng_payload_keeps_guofeng_not_realvis():
    from app.image_jobs import _t2i_payload

    project = Project(id="p", title="t", style="国风3D、东方江湖", source_text="x")
    male = Asset(
        id="a1",
        project_id="p",
        kind="character",
        name="林砚之",
        refer_as="少年",
        age_band="17岁",
        desc_zh="清瘦少年，洗白长衫",
    )
    payload = _t2i_payload(male, project, "full", "9:16")
    assert payload["style"] == "guofeng_cg"
    assert payload.get("prefer_backend") != "sdxl_realvis"
    assert payload["gender"] == "male"


def test_enrich_no_longer_hardcodes_woman_for_male():
    out = enrich_character_prompt(
        "半写实。男性。全身站立。",
        "guofeng",
        gender="male",
        age_tier="youth",
    )
    assert "woman" not in out.lower()
    assert "man" in out.lower() or "1boy" in out.lower() or "one man" in out.lower()


def test_elder_negative_blocks_young():
    neg = identity_negative(gender="female", age_tier="elder")
    assert "young" in neg
    assert "少女" in neg


def test_identity_lock_zh_grandma():
    lock = identity_lock_zh(gender="female", age_tier="elder", refer_as="婆婆", age_band="60岁")
    assert "老年女性" in lock


def test_infer_male_from_大人_and_知县():
    assert infer_gender(name="周大人", refer_as="知县", age_band="middle-aged", look="穿着官服") == "male"
    assert infer_age_tier(name="周大人", refer_as="知县", age_band="middle-aged", look="") == "adult"


def test_infer_male_assassin_and_elder_from_老人():
    assert infer_gender(name="黑衣人", refer_as="刺客", age_band="", look="黑衣蒙面") == "male"
    assert infer_gender(name="陈守义", refer_as="老人", age_band="", look="") == "male"
    assert infer_age_tier(name="陈守义", refer_as="老人", age_band="", look="") == "elder"


def test_half_prompt_is_reframe_not_redesign():
    project = Project(id="p", title="t", style="国漫3D", source_text="x")
    asset = Asset(
        id="a1",
        project_id="p",
        kind="character",
        name="周大人",
        refer_as="知县",
        age_band="middle-aged",
        desc_zh="穿着官服，中年面容",
    )
    text = build_field_prompt(project, asset, "half")
    assert "半身" in text or "胸像" in text
    assert "同一人物" in text or "参考" in text
    # Must not push a costume redesign that fights the full-body reference image
    assert "汉服或江湖劲装" not in text
    assert "禁止换" in text
    # Look prose must not be injected (it caused half to ignore the full reference)
    assert "穿着官服" not in text


def test_prop_prompt_is_object_not_narrative_scene():
    project = Project(id="p", title="t", style="国漫3D", source_text="x")
    prop = Asset(
        id="p1",
        project_id="p",
        kind="prop",
        name="玉佩",
        desc_zh="分为两半，一半在林砚之手中，一半在陈守义手中，合在一起可以打开藏匿文献的地方，上面刻有忠守二字。",
    )
    text = build_field_prompt(project, prop, "image")
    assert "玉佩" in text
    assert "不要人物" in text or "禁止人物" in text
    assert "不要" in text and ("建筑" in text or "场景" in text or "风景" in text)
    assert "手中" not in text
    assert "玉佩坠" in text or "古玉" in text
    assert "聚光灯" in text or "摄影灯" in text
