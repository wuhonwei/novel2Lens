"""Identity binding helpers for multi-reference Qwen Image Edit (first frames)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.domain.registry import normalize_kind


def _appearance(asset: Any) -> dict[str, Any]:
    raw = getattr(asset, "appearance_json", None) or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _clip(text: str, n: int = 24) -> str:
    t = re.sub(r"\s+", "", (text or "").strip())
    if len(t) <= n:
        return t
    return t[:n]


def _age_token(asset: Any) -> str:
    refer = (getattr(asset, "refer_as", None) or "").strip()
    if refer and refer not in ("人", "人物"):
        return refer
    age = (getattr(asset, "age_band", None) or "").strip()
    return age


def _look_tokens(asset: Any) -> list[str]:
    """Short face/hair anchors. Skip appearance.clothing — asset text often lags the ref image."""
    app = _appearance(asset)
    out: list[str] = []
    for key in ("face", "hair"):
        val = _clip(str(app.get(key) or ""), 18)
        if val and val not in out:
            out.append(val)
    blob = "".join(out) + (getattr(asset, "desc_zh", None) or "")
    refer = (getattr(asset, "refer_as", None) or "").strip()
    if any(k in blob for k in ("须", "髯", "胡")) or refer in ("老人", "婆婆", "爷爷", "老者"):
        if not any("须" in x for x in out):
            out.insert(0, "白须" if ("白" in blob or refer in ("老人", "婆婆", "爷爷", "老者")) else "有胡须")
    elif refer in ("少年", "青年", "少女", "女孩", "男孩"):
        out.insert(0, "无胡须")
    return out[:3]


def garment_tone_hint(image_path: str | Path) -> str:
    """Coarse garment brightness from a character sheet (torso band)."""
    try:
        from PIL import Image

        img = Image.open(str(image_path)).convert("RGB")
        w, h = img.size
        band = img.crop((int(w * 0.25), int(h * 0.35), int(w * 0.75), int(h * 0.70))).resize((48, 32))
        px = list(band.getdata())
        if not px:
            return ""
        lumas = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
        mean = sum(lumas) / max(1, len(lumas))
        if mean < 85:
            return "DARK garments as in ref"
        if mean > 155:
            return "LIGHT garments as in ref"
        return "mid-tone garments as in ref"
    except Exception:
        return ""


def edit_ref_label(asset: Any | None, image_role: str, *, image_path: str | Path | None = None) -> str:
    """Distinct slot label for Comfy 'Using image N (label)' binding."""
    role = (image_role or "reference").strip() or "reference"
    if not asset:
        return role
    name = (getattr(asset, "name", None) or "").strip()
    kind = normalize_kind(getattr(asset, "kind", "") or "")
    if kind == "prop":
        return f"{name}·{role}" if name else role
    if kind == "scene":
        return f"{name}·{role}" if name else role
    if kind != "character":
        return f"{name}·{role}" if name else role

    # Keep labels SHORT — long Chinese face prose inside the English wrapper
    # confuses Qwen Edit and can drop the second person entirely.
    parts: list[str] = []
    if name:
        parts.append(name)
    age = _age_token(asset)
    if age and age not in parts:
        parts.append(age)
    look = _look_tokens(asset)
    # Prefer beard / no-beard token only (first look token if it is that)
    if look:
        parts.append(look[0])
    tone = garment_tone_hint(image_path) if image_path else ""
    if tone:
        parts.append(tone)
    parts.append("outfit+face exact from this ref")
    if "半身" in role:
        parts.append("half-body")
    else:
        parts.append("full-body")
    return "·".join(parts)


def wrap_multi_char_first_frame(
    *,
    labeled: list[str],
    edit_prompt: str,
    aspect: str,
    width: int,
    height: int,
) -> str:
    """English wrapper that binds each person slot to its own reference label."""
    person_bits: list[str] = []
    for i, lab in enumerate(labeled):
        # labeled entries look like "image 1 (…)"
        m = re.match(r"image\s+(\d+)\s*\((.+)\)\s*$", lab.strip(), re.I)
        if not m:
            continue
        idx, inner = m.group(1), m.group(2)
        # Skip pure prop/scene when no person cues — still bind if label has person name cues
        if "物品" in inner or "场景" in inner or "prop" in inner.lower() or "scene" in inner.lower():
            person_bits.append(
                f"image {idx} is a prop/scene reference only ({inner}); do not turn it into an extra face."
            )
            continue
        person_bits.append(
            f"The person described as matching image {idx} must match ONLY from image {idx} "
            f"({inner}): same face, age, hair, beard/no-beard, and outfit. "
            f"Do not borrow facial features from any other image."
        )
    binding = " ".join(person_bits) if person_bits else (
        "Each labeled person reference is a DIFFERENT identity."
    )
    person_count = sum(
        1
        for lab in labeled
        if not any(k in lab for k in ("物品", "场景", "prop", "scene", "Prop", "Scene"))
    )
    count_lock = ""
    if person_count >= 2:
        count_lock = (
            f"MANDATORY: the output must show ALL {person_count} people from the person references "
            f"together in one frame (exactly {person_count} identifiable faces). "
            "Never drop a person; never output a solo portrait. "
            "Standing order: the leftmost named person must be the identity from image 1; "
            "the rightmost named person must be the identity from image 2 "
            "(unless the Chinese prompt explicitly swaps them). "
            "Copy each character reference's garment COLOR and silhouette exactly "
            "(dark armor stays dark; light scholar robes stay light). "
            "Do not recolor outfits to match each other. "
        )
    return (
        f"Using {', '.join(labeled)}, create one new image: {edit_prompt}. "
        f"CRITICAL: {count_lock}{binding} "
        "Do not clone one face onto both people. Never give two people the same white beard "
        "unless BOTH person references clearly show white beards. "
        "If one reference is a youth without a beard and another is an elder with a beard, "
        "keep that age/beard contrast exactly. "
        f"Output image aspect ratio {aspect}, resolution {width}x{height}."
    )


def multi_char_first_frame_negative() -> str:
    return (
        "identical faces, cloned face, same face on two people, duplicated character, "
        "both people same age, two identical white beards, matching twins, "
        "face swap, identity collapse, same outfit on both people, "
        "solo portrait, single person only, only one character, missing second person, "
        "one person alone, cropped to one face, "
        "两个相同的脸, 复制同一张脸, 两人都是白胡子老人, 换脸, 只剩一个人, 单人肖像"
    )


def wrap_two_pass_stage1(
    *,
    label: str,
    edit_prompt: str,
    aspect: str,
    width: int,
    height: int,
) -> str:
    """Pass 1: place ONLY person from image 1 on the left; leave room on the right."""
    return (
        f"Using image 1 ({label}), create one new image: {edit_prompt}. "
        "CRITICAL: show ONLY one identifiable person — the person from image 1 "
        f"({label}) standing on the LEFT side of the frame, facing as instructed. "
        "Match that reference's face, age, hair, beard/no-beard, outfit color and silhouette exactly. "
        "Leave clear empty space / room on the right for a second person to be added later. "
        "Do not invent a second named character; distant unrecognizable silhouettes only. "
        f"Output image aspect ratio {aspect}, resolution {width}x{height}."
    )


def wrap_two_pass_stage2(
    *,
    base_label: str,
    person2_label: str,
    edit_prompt: str,
    aspect: str,
    width: int,
    height: int,
    person1_lock_label: str = "",
) -> str:
    """Pass 2: keep pass1 plate; add person 2 on the right from their reference."""
    lock = ""
    if person1_lock_label:
        lock = (
            f" image 2 ({person1_lock_label}) is the LEFT person's identity lock — "
            "the left figure must keep matching image 2's face/outfit; "
        )
        refs = (
            f"Using image 1 ({base_label}), image 2 ({person1_lock_label}), "
            f"image 3 ({person2_label}), create one new image: {edit_prompt}. "
        )
        add_idx = "image 3"
    else:
        refs = (
            f"Using image 1 ({base_label}), image 2 ({person2_label}), "
            f"create one new image: {edit_prompt}. "
        )
        add_idx = "image 2"
    return (
        f"{refs}"
        "CRITICAL: image 1 is the composition plate — KEEP the left person, scene, lighting, "
        "and camera framing from image 1 unchanged (same face, hair, outfit)."
        f"{lock}"
        f" COMPOSITE ADD: place a NEW full-body person from {add_idx} ({person2_label}) "
        "clearly on the RIGHT half of the frame, physically separated from the left person "
        "(do not overlap faces). "
        f"The right person must match ONLY {add_idx} for face, age, hair, beard/no-beard, and outfit. "
        "Do not clone the left person's face onto the right. "
        "MANDATORY: exactly 2 identifiable people (both people visible). "
        "Copy garment COLOR and silhouette from each person's own reference. "
        f"Output image aspect ratio {aspect}, resolution {width}x{height}."
    )


def two_pass_stage1_negative() -> str:
    return (
        "two people, second person, pair of characters, dual portrait, couple standing, "
        "extra face, another man beside, 双人, 第二个人, 两人同框, "
        "identical twin, white beard on youth, elderly clone"
    )


def person_ref_indices(ref_labels: list[str]) -> list[int]:
    """Indices of character refs (skip prop/scene labels)."""
    out: list[int] = []
    for i, lab in enumerate(ref_labels):
        s = (lab or "").strip()
        if any(k in s for k in ("物品", "场景", "prop", "scene", "Prop", "Scene")):
            continue
        out.append(i)
    return out
