from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image

FitMode = Literal["cover", "contain", "stretch"]


def fit_image(
    src: Path | Image.Image,
    width: int,
    height: int,
    mode: FitMode = "cover",
    *,
    fill_color: tuple[int, int, int] = (0, 0, 0),
) -> Image.Image:
    img = src.convert("RGB") if isinstance(src, Image.Image) else Image.open(src).convert("RGB")
    tw, th = int(width), int(height)
    if tw < 1 or th < 1:
        raise ValueError("target size must be positive")

    if mode == "stretch":
        return img.resize((tw, th), Image.Resampling.LANCZOS)

    sw, sh = img.size
    scale_w = tw / sw
    scale_h = th / sh

    if mode == "cover":
        scale = max(scale_w, scale_h)
        nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
        resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
        left = max(0, (nw - tw) // 2)
        top = max(0, (nh - th) // 2)
        return resized.crop((left, top, left + tw, top + th))

    scale = min(scale_w, scale_h)
    nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (tw, th), fill_color)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def save_fitted(
    src: Path,
    dest: Path,
    width: int,
    height: int,
    mode: FitMode = "cover",
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = fit_image(src, width, height, mode)
    out.save(dest, format="PNG")
    return dest
