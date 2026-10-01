from app.comfy_pipeline.qa import assess_dual_character_presence, assess_image_bytes
from PIL import Image
import io


def _png(w: int, h: int, paint) -> bytes:
    img = Image.new("RGB", (w, h), (40, 80, 100))  # cool bg
    paint(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_dual_presence_fails_when_only_center_person():
    def paint(img):
        px = img.load()
        w, h = img.size
        # one skin blob in center only
        for y in range(h // 4, 3 * h // 4):
            for x in range(w // 2 - 40, w // 2 + 40):
                px[x, y] = (210, 160, 130)

    data = _png(640, 360, paint)
    r = assess_dual_character_presence(Image.open(io.BytesIO(data)).convert("RGB"))
    assert r == "missing_second_character"


def test_dual_presence_passes_with_left_and_right_skin():
    def paint(img):
        px = img.load()
        w, h = img.size
        for y in range(h // 5, 3 * h // 4):
            for x in range(40, 120):
                px[x, y] = (205, 155, 125)
            for x in range(w - 120, w - 40):
                px[x, y] = (200, 150, 120)

    data = _png(640, 360, paint)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    assert assess_dual_character_presence(img) is None
    out = assess_image_bytes(data, min_character_sides=2)
    assert out["ok"] is True


def test_right_companion_delta_detects_added_person():
    from app.comfy_pipeline.qa import assess_companion_added

    def _png(w, h, paint):
        img = Image.new("RGB", (w, h), (40, 80, 100))
        paint(img)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def solo(img):
        px = img.load()
        w, h = img.size
        for y in range(h // 5, 3 * h // 4):
            for x in range(40, 100):
                px[x, y] = (205, 155, 125)

    def duo(img):
        solo(img)
        px = img.load()
        w, h = img.size
        for y in range(h // 5, 3 * h // 4):
            for x in range(w - 120, w - 40):
                px[x, y] = (200, 150, 120)

    before = _png(640, 360, solo)
    after = _png(640, 360, duo)
    assert assess_companion_added(before, after, slot="right") is None
    assert assess_companion_added(before, before, slot="right") == "missing_second_character"


def test_identity_collapse_fails_when_both_sides_are_white_haired_elders():
    from app.comfy_pipeline.qa import assess_dual_identity_collapse

    def paint(img):
        px = img.load()
        w, h = img.size
        # Two elder-like figures: skin + bright white hair crowns on BOTH sides.
        for y in range(h // 5, 3 * h // 4):
            for x in range(40, 120):
                px[x, y] = (205, 155, 125)
            for x in range(w - 120, w - 40):
                px[x, y] = (200, 150, 120)
        for y in range(h // 8, h // 4):
            for x in range(50, 110):
                px[x, y] = (235, 235, 230)
            for x in range(w - 110, w - 50):
                px[x, y] = (232, 232, 228)

    data = _png(640, 360, paint)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    assert assess_dual_identity_collapse(img, require_age_contrast=True) == "identity_collapse"


def test_identity_collapse_passes_youth_left_elder_right():
    from app.comfy_pipeline.qa import assess_dual_identity_collapse

    def paint(img):
        px = img.load()
        w, h = img.size
        # Left: youth — dark hair crown, skin face
        for y in range(h // 5, 3 * h // 4):
            for x in range(40, 120):
                px[x, y] = (205, 155, 125)
        for y in range(h // 8, h // 4):
            for x in range(50, 110):
                px[x, y] = (25, 20, 18)  # black hair
        # Right: elder — white hair crown
        for y in range(h // 5, 3 * h // 4):
            for x in range(w - 120, w - 40):
                px[x, y] = (200, 150, 120)
        for y in range(h // 8, h // 4):
            for x in range(w - 110, w - 50):
                px[x, y] = (235, 235, 230)

    data = _png(640, 360, paint)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    assert assess_dual_identity_collapse(img, require_age_contrast=True) is None


def test_person_labels_age_conflict_helper():
    from app.domain.edit_identity import person_labels_age_conflict

    assert person_labels_age_conflict(
        [
            "林砚之·少年·无胡须·LIGHT garments",
            "陈守义·老人·白须·DARK garments",
        ]
    )
    assert not person_labels_age_conflict(
        [
            "林砚之·少年·无胡须",
            "苏婉清·少女·无胡须",
        ]
    )
