"""Image QA helpers — ported from aiImage (zaoxiang.qa)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class QaResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    mean_luma: float = 0.0
    variance: float = 0.0


def _is_ideogram_safety_gray(img) -> bool:
    import statistics

    small = img.resize((96, 64))
    px = list(small.getdata())
    if not px:
        return False
    chromas = [abs(r - g) + abs(g - b) + abs(b - r) for r, g, b in px]
    mean_chroma = statistics.fmean(chromas)
    lumas = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
    mean_l = statistics.fmean(lumas)
    var_l = statistics.pvariance(lumas) if len(lumas) > 1 else 0.0
    if mean_chroma <= 18 and 70 <= mean_l <= 200 and var_l <= 1200:
        w, h = small.size
        cy0, cy1 = h // 3, 2 * h // 3
        cx0, cx1 = w // 6, 5 * w // 6
        center = []
        border = []
        for y in range(h):
            for x in range(w):
                L = lumas[y * w + x]
                if cy0 <= y < cy1 and cx0 <= x < cx1:
                    center.append(L)
                elif x < 8 or x >= w - 8 or y < 6 or y >= h - 6:
                    border.append(L)
        if center and border and statistics.fmean(center) - statistics.fmean(border) >= 8:
            return True
        if mean_chroma <= 10 and var_l <= 400:
            return True
    return False


def _band_edge_energy(img, y0_frac: float, y1_frac: float) -> float:
    w, h = img.size
    y0 = max(0, int(h * y0_frac))
    y1 = min(h, max(y0 + 1, int(h * y1_frac)))
    band = img.crop((0, y0, w, y1)).resize((64, max(8, (y1 - y0) * 64 // max(1, h))))
    px = band.load()
    bw, bh = band.size
    energy = 0.0
    n = 0
    for y in range(bh - 1):
        for x in range(bw - 1):
            r1, g1, b1 = px[x, y]
            r2, g2, b2 = px[x + 1, y]
            r3, g3, b3 = px[x, y + 1]
            l1 = 0.299 * r1 + 0.587 * g1 + 0.114 * b1
            l2 = 0.299 * r2 + 0.587 * g2 + 0.114 * b2
            l3 = 0.299 * r3 + 0.587 * g3 + 0.114 * b3
            energy += abs(l1 - l2) + abs(l1 - l3)
            n += 1
    return energy / max(1, n)


def assess_fullbody_framing(img) -> str | None:
    w, h = img.size
    if h < w * 1.05:
        return None
    bottom = _band_edge_energy(img, 0.88, 1.0)
    mid = _band_edge_energy(img, 0.35, 0.55)
    if mid < 1.5:
        return None
    if bottom / mid < 0.28:
        return "fullbody_feet_missing"
    return None


def _skinish(r: int, g: int, b: int) -> bool:
    """Loose skin cue for stylized 3D / guoman (not photographic Fitzpatrick).

    Includes ashen/elderly tones common in 国风3D elders (苏婆婆 etc.).
    """
    if r < 70 or g < 45 or b < 35:
        return False
    if r + 12 < g or r + 10 < b:
        return False
    # Exclude warm lantern / bread yellows (high R≈G, very low B).
    if b < 90 and r > 160 and g > 130 and abs(r - g) < 45 and (r - b) > 70:
        return False
    if max(r, g, b) - min(r, g, b) < 16:
        return False  # near-gray mist / stone
    return True


def assess_right_companion_added(before_png: bytes, after_png: bytes) -> str | None:
    """Backward-compatible alias: right-slot companion delta."""
    return assess_companion_added(before_png, after_png, slot="right")


def assess_companion_added(
    before_png: bytes,
    after_png: bytes,
    *,
    slot: str = "right",
    min_score: float = 10.0,
) -> str | None:
    """Sequential multi-char stage: target standing slot must change vs previous plate."""
    import io
    from PIL import Image, ImageChops

    try:
        before = Image.open(io.BytesIO(before_png)).convert("L").resize((168, 96))
        after = Image.open(io.BytesIO(after_png)).convert("L").resize((168, 96))
    except Exception:
        return "unreadable_pair"
    boxes = {
        "left": (0, 8, 70, 72),
        "center": (49, 8, 119, 72),
        "right": (100, 8, 168, 72),
    }
    box = boxes.get((slot or "right").lower(), boxes["right"])
    diff = ImageChops.difference(before.crop(box), after.crop(box))
    score = sum(diff.getdata()) / max(1, diff.size[0] * diff.size[1])
    if score < float(min_score):
        return "missing_second_character"
    return None


def assess_dual_character_presence(img) -> str | None:
    """Require separated skin peaks on left AND right (reject one centered person)."""
    w, h = img.size
    small = img.resize((max(160, w // 8), max(90, h // 8)))
    sw, sh = small.size
    px = small.load()
    y0, y1 = int(sh * 0.10), int(sh * 0.65)
    left_x1 = int(sw * 0.40)
    right_x0 = int(sw * 0.60)
    win = max(10, min(sw, sh) // 7)

    def peak(x0: int, x1: int) -> tuple[int, float]:
        best = 0
        best_cx = (x0 + x1) / 2
        x0 = max(0, x0)
        x1 = min(sw, x1)
        if x1 - x0 < win or y1 - y0 < win:
            return 0, best_cx
        for y in range(y0, y1 - win + 1, max(1, win // 3)):
            for x in range(x0, x1 - win + 1, max(1, win // 3)):
                n = 0
                for yy in range(y, y + win):
                    for xx in range(x, x + win):
                        r, g, b = px[xx, yy]
                        if _skinish(r, g, b):
                            n += 1
                if n > best:
                    best = n
                    best_cx = x + win / 2
        return best, best_cx

    left_peak, left_cx = peak(0, left_x1)
    right_peak, right_cx = peak(right_x0, sw)
    # Stylized 3D / elder skin reads thinner than photo — keep floor modest.
    need = max(12, (win * win) // 12)
    if left_peak < need or right_peak < need:
        return "missing_second_character"
    if (right_cx - left_cx) < sw * 0.22:
        return "missing_second_character"
    return None


def _white_hair_score(img, x0: int, x1: int, y0: int, y1: int) -> float:
    """Fraction of near-white low-chroma pixels in a head band (elder hair cue)."""
    px = img.load()
    w, h = img.size
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    hit = 0
    tot = 0
    for y in range(y0, y1, max(1, (y1 - y0) // 24)):
        for x in range(x0, x1, max(1, (x1 - x0) // 24)):
            r, g, b = px[x, y]
            tot += 1
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            chroma = abs(r - g) + abs(g - b) + abs(b - r)
            if luma >= 185 and chroma <= 45:
                hit += 1
    return hit / max(1, tot)


def _dark_hair_score(img, x0: int, x1: int, y0: int, y1: int) -> float:
    """Fraction of dark low-chroma pixels in a head band (youth black hair cue)."""
    px = img.load()
    w, h = img.size
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    hit = 0
    tot = 0
    for y in range(y0, y1, max(1, (y1 - y0) // 24)):
        for x in range(x0, x1, max(1, (x1 - x0) // 24)):
            r, g, b = px[x, y]
            tot += 1
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            chroma = abs(r - g) + abs(g - b) + abs(b - r)
            if luma <= 70 and chroma <= 55:
                hit += 1
    return hit / max(1, tot)


def assess_dual_identity_collapse(img, *, require_age_contrast: bool = False) -> str | None:
    """Reject twin elders when youth+elder contrast was required.

    Heuristic: both standing slots look elder-haired (bright white crown dominates
    dark hair). Used after dual-presence passes.
    """
    if not require_age_contrast:
        return None
    w, h = img.size
    # Head bands on left / right thirds.
    y0, y1 = int(h * 0.05), int(h * 0.32)
    left_white = _white_hair_score(img, 0, int(w * 0.38), y0, y1)
    right_white = _white_hair_score(img, int(w * 0.62), w, y0, y1)
    left_dark = _dark_hair_score(img, 0, int(w * 0.38), y0, y1)
    right_dark = _dark_hair_score(img, int(w * 0.62), w, y0, y1)
    left_elder = left_white >= 0.08 and left_white >= left_dark * 0.9
    right_elder = right_white >= 0.08 and right_white >= right_dark * 0.9
    if left_elder and right_elder:
        return "identity_collapse"
    return None


def assess_image_bytes(
    data: bytes,
    *,
    min_side: int = 256,
    near_black_mean: float = 12.0,
    near_white_mean: float = 250.0,
    low_variance: float = 8.0,
    require_fullbody: bool = False,
    min_character_sides: int = 0,
    require_identity_contrast: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return dict with ok/passed for worker compatibility."""
    _ = kwargs
    reasons: list[str] = []
    try:
        from PIL import Image
        import io
        import statistics

        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        w, h = img.size
        if w < min_side or h < min_side:
            reasons.append("too_small")
        if _is_ideogram_safety_gray(img):
            reasons.append("safety_filter_blocked")
        step_x = max(1, w // 64)
        step_y = max(1, h // 64)
        samples: list[float] = []
        px = img.load()
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                r, g, b = px[x, y]
                samples.append(0.299 * r + 0.587 * g + 0.114 * b)
        mean = float(statistics.fmean(samples)) if samples else 0.0
        var = float(statistics.pvariance(samples)) if len(samples) > 1 else 0.0
        if mean <= near_black_mean:
            reasons.append("near_black")
        if mean >= near_white_mean:
            reasons.append("near_white")
        if var <= low_variance and "too_small" not in reasons and "safety_filter_blocked" not in reasons:
            reasons.append("flat_image")
        if require_fullbody and not reasons:
            fb = assess_fullbody_framing(img)
            if fb:
                reasons.append(fb)
        if int(min_character_sides or 0) >= 2 and not reasons:
            dual = assess_dual_character_presence(img)
            if dual:
                reasons.append(dual)
        if (require_identity_contrast or int(min_character_sides or 0) >= 2) and not reasons:
            # Only enforce twin-elder rejection when contrast was requested.
            if require_identity_contrast:
                coll = assess_dual_identity_collapse(img, require_age_contrast=True)
                if coll:
                    reasons.append(coll)
        result = QaResult(
            passed=len(reasons) == 0,
            reasons=reasons,
            width=w,
            height=h,
            mean_luma=mean,
            variance=var,
        )
    except Exception as exc:  # noqa: BLE001
        result = QaResult(passed=False, reasons=[f"unreadable:{type(exc).__name__}"])
    d = asdict(result)
    d["ok"] = result.passed
    return d
