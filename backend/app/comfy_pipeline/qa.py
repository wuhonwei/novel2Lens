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


def assess_image_bytes(
    data: bytes,
    *,
    min_side: int = 256,
    near_black_mean: float = 12.0,
    near_white_mean: float = 250.0,
    low_variance: float = 8.0,
    require_fullbody: bool = False,
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
