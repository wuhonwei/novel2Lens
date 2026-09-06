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
            for x in range(30, 90):
                px[x, y] = (205, 155, 125)
            for x in range(w - 90, w - 30):
                px[x, y] = (200, 150, 120)

    data = _png(640, 360, paint)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    assert assess_dual_character_presence(img) is None
    out = assess_image_bytes(data, min_character_sides=2)
    assert out["ok"] is True


def test_assess_image_bytes_flags_solo_when_min_sides_2():
    def paint(img):
        px = img.load()
        w, h = img.size
        for y in range(h // 4, 3 * h // 4):
            for x in range(w // 2 - 50, w // 2 + 50):
                px[x, y] = (210, 160, 130)

    data = _png(640, 360, paint)
    out = assess_image_bytes(data, min_character_sides=2)
    assert out["ok"] is False
    assert "missing_second_character" in out["reasons"]
