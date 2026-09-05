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
    g = build_field_prompt(project, grandma, "full")
    assert "老年" in g or "苍老" in g
    assert "不可年轻化" in g or "皱纹" in g


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
