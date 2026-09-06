"""Distinct identity labels for multi-character first-frame Qwen edits."""

from app.domain.edit_identity import (
    edit_ref_label,
    wrap_multi_char_first_frame,
    multi_char_first_frame_negative,
)


class _A:
    def __init__(self, **kw):
        self.__dict__.update(
            {
                "kind": "character",
                "name": "",
                "refer_as": "",
                "age_band": "",
                "appearance_json": "{}",
                "desc_zh": "",
            }
        )
        self.__dict__.update(kw)


def test_character_edit_labels_are_distinct_and_named():
    lin = _A(
        name="林砚之",
        refer_as="少年",
        age_band="17岁",
        appearance_json='{"hair":"黑色短发束冠","face":"无胡须","clothing":"黑色劲装铠甲"}',
    )
    chen = _A(
        name="陈守义",
        refer_as="老人",
        age_band="老年",
        appearance_json='{"hair":"白发白须","face":"长白须","clothing":"浅灰蓝长袍"}',
    )
    lab1 = edit_ref_label(lin, "人物全身图")
    lab2 = edit_ref_label(chen, "人物全身图")
    assert "林砚之" in lab1 and "陈守义" in lab2
    assert lab1 != lab2
    assert "少年" in lab1 or "17" in lab1
    assert "老人" in lab2 or "白须" in lab2 or "老年" in lab2
    # Must not be the old identical generic role alone
    assert lab1 != "人物全身图"
    assert lab2 != "人物全身图"


def test_garment_tone_hint_dark_vs_light(tmp_path):
    from PIL import Image
    from app.domain.edit_identity import garment_tone_hint, edit_ref_label

    dark = tmp_path / "dark.png"
    light = tmp_path / "light.png"
    Image.new("RGB", (128, 256), (20, 20, 25)).save(dark)
    Image.new("RGB", (128, 256), (210, 210, 215)).save(light)
    assert "DARK" in garment_tone_hint(dark)
    assert "LIGHT" in garment_tone_hint(light)
    lin = _A(name="林砚之", refer_as="少年", age_band="17岁", appearance_json="{}")
    lab = edit_ref_label(lin, "人物全身图", image_path=dark)
    assert "DARK" in lab



def test_prop_edit_label_keeps_role_with_name():
    prop = _A(kind="prop", name="玉佩", appearance_json="{}")
    lab = edit_ref_label(prop, "核心物品参考图")
    assert "玉佩" in lab
    assert "核心物品" in lab or "物品" in lab


def test_multi_char_wrap_binds_each_image_to_its_label():
    labeled = [
        "image 1 (林砚之·少年·无胡须·outfit+face exact from this ref·full-body)",
        "image 2 (陈守义·老人·白须·outfit+face exact from this ref·full-body)",
        "image 3 (玉佩·核心物品参考图)",
    ]
    wrapped = wrap_multi_char_first_frame(
        labeled=labeled,
        edit_prompt="图一递玉佩。图二接玉佩。",
        aspect="16:9",
        width=1344,
        height=768,
    )
    assert "image 1 (林砚之" in wrapped
    assert "image 2 (陈守义" in wrapped
    # Per-slot binding in CRITICAL
    assert "image 1" in wrapped and "林砚之" in wrapped
    assert "must match only image 1" in wrapped.lower() or "only from image 1" in wrapped.lower()
    assert "only from image 2" in wrapped.lower() or "must match only image 2" in wrapped.lower()
    assert "white beard" in wrapped.lower() or "beard" in wrapped.lower()
    assert "1344x768" in wrapped
    assert "exactly 2" in wrapped.lower() or "ALL 2" in wrapped
    assert "solo portrait" in wrapped.lower() or "Never drop" in wrapped
    assert "leftmost" in wrapped.lower() and "image 1" in wrapped.lower()
    assert "garment" in wrapped.lower() or "silhouette" in wrapped.lower()


def test_multi_char_negative_blocks_face_clone():
    neg = multi_char_first_frame_negative()
    low = neg.lower()
    assert "identical" in low or "clone" in low or "same face" in low
    assert "beard" in low or "白须" in neg
    assert "solo" in low or "single person" in low or "只剩一个人" in neg


def test_two_pass_stage_wraps():
    from app.domain.edit_identity import (
        wrap_two_pass_stage1,
        wrap_two_pass_stage2,
        two_pass_stage1_negative,
        person_ref_indices,
    )

    s1 = wrap_two_pass_stage1(
        label="林砚之·少年·无胡须·DARK garments as in ref·full-body",
        edit_prompt="图一低头。图二站着不动。",
        aspect="16:9",
        width=1344,
        height=768,
    )
    assert "image 1 (林砚之" in s1
    assert "ONLY one identifiable person" in s1 or "exactly 1" in s1.lower()
    assert "left" in s1.lower()
    assert "empty space" in s1.lower() or "room on the right" in s1.lower()
    assert "1344x768" in s1

    s2 = wrap_two_pass_stage2(
        base_label="pass1 composition plate",
        person2_label="陈守义·老人·白须·mid-tone garments as in ref·full-body",
        edit_prompt="图一低头。图二站着不动。",
        aspect="16:9",
        width=1344,
        height=768,
        person1_lock_label="林砚之·少年·无胡须·DARK garments as in ref·full-body",
    )
    assert "image 1 (pass1" in s2
    assert "image 2 (林砚之" in s2
    assert "image 3 (陈守义" in s2
    assert "COMPOSITE ADD" in s2 or "ADD" in s2
    assert "right" in s2.lower()
    assert "exactly 2" in s2.lower() or "ALL 2" in s2 or "both people" in s2.lower()
    assert "do not change" in s2.lower() or "KEEP" in s2 or "keep" in s2.lower()

    neg = two_pass_stage1_negative()
    assert "second person" in neg.lower() or "two people" in neg.lower() or "双人" in neg
    assert person_ref_indices(
        ["林砚之·少年", "陈守义·老人", "玉佩·核心物品参考图"]
    ) == [0, 1]
