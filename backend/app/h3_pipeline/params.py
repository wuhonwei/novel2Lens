from __future__ import annotations

import math
from typing import Literal

FitMode = Literal["cover", "contain", "stretch"]
AspectRatio = Literal["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9"]
Clarity = Literal["0.5", "0.75", "0.98"]

ASPECT_RATIOS: dict[str, tuple[float, float]] = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "3:2": (3, 2),
    "2:3": (2, 3),
    "21:9": (21, 9),
}

CLARITY_MP: dict[str, float] = {
    "0.5": 0.5,
    "0.75": 0.75,
    "0.98": 0.98,
}

FPS = 24
CANVAS_MULTIPLE = 32
TRAINED_MAX_SECONDS = 15.0
MAX_PIXELS = 768 * 1344
BASE_SHORT_EDGE = 768


def align_frame_count(n: int) -> int:
    n = max(5, int(n))
    while n % 17 != 5:
        n += 1
    return n


def seconds_to_frames(seconds: float) -> int:
    raw = max(5, round(float(seconds) * FPS))
    return align_frame_count(raw)


def frames_to_seconds(frames: int) -> float:
    return align_frame_count(frames) / FPS


def round_to_multiple(value: float, multiple: int = CANVAS_MULTIPLE) -> int:
    return max(multiple, int(round(value / multiple) * multiple))


def resolution_from_aspect_clarity(aspect: str, clarity: str) -> tuple[int, int]:
    if aspect not in ASPECT_RATIOS:
        raise ValueError(f"unsupported aspect: {aspect}")
    if clarity not in CLARITY_MP:
        raise ValueError(f"unsupported clarity: {clarity}")
    aw, ah = ASPECT_RATIOS[aspect]

    if clarity == "0.98":
        if aw >= ah:
            h = BASE_SHORT_EDGE
            w = round_to_multiple(BASE_SHORT_EDGE * aw / ah)
        else:
            w = BASE_SHORT_EDGE
            h = round_to_multiple(BASE_SHORT_EDGE * ah / aw)
        if w * h > MAX_PIXELS:
            scale = math.sqrt(MAX_PIXELS / (w * h))
            w = round_to_multiple(w * scale)
            h = round_to_multiple(h * scale)
        return w, h

    megapixels = CLARITY_MP[clarity]
    target_pixels = megapixels * 1_000_000
    height = math.sqrt(target_pixels * ah / aw)
    width = height * aw / ah
    w = round_to_multiple(width)
    h = round_to_multiple(height)
    if w * h > target_pixels * 1.15:
        scale = math.sqrt(target_pixels / (w * h))
        w = round_to_multiple(w * scale)
        h = round_to_multiple(h * scale)
    return w, h


def steps_for_turbo(turbo: bool, *, voice: bool = False) -> int:
    if not turbo:
        return 20
    return 4 if voice else 8
