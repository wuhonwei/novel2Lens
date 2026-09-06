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


def test_sequential_place_wraps_for_three_people():
    from app.domain.edit_identity import (
        standing_slot,
        wrap_sequential_place_first,
        wrap_sequential_add_person,
    )

    assert standing_slot(0, 2) == "left"
    assert standing_slot(1, 2) == "right"
    assert standing_slot(0, 3) == "left"
    assert standing_slot(1, 3) == "center"
    assert standing_slot(2, 3) == "right"

    s1 = wrap_sequential_place_first(
        label="林砚之·少年",
        edit_prompt="三人同框。",
        total_people=3,
        aspect="16:9",
        width=1344,
        height=768,
    )
    assert "ONLY one identifiable person" in s1
    assert "left" in s1.lower()
    assert "2 more" in s1.lower() or "two more" in s1.lower() or "room" in s1.lower()

    s2 = wrap_sequential_add_person(
        base_label="plate",
        new_label="陈守义·老人",
        lock_labels=["林砚之·少年"],
        person_index=1,
        total_people=3,
        edit_prompt="三人同框。",
        aspect="16:9",
        width=1344,
        height=768,
    )
    assert "center" in s2.lower()
    assert "exactly 2" in s2.lower() or "2 identifiable" in s2.lower()
    assert "林砚之" in s2
    assert "陈守义" in s2

    s3 = wrap_sequential_add_person(
        base_label="plate",
        new_label="苏晚卿·少女",
        lock_labels=["林砚之·少年", "陈守义·老人"],
        person_index=2,
        total_people=3,
        edit_prompt="三人同框。",
        aspect="16:9",
        width=1344,
        height=768,
    )
    assert "right" in s3.lower()
    assert "exactly 3" in s3.lower() or "3 identifiable" in s3.lower()
    assert "苏晚卿" in s3
