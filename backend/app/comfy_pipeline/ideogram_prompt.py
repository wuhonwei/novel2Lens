from __future__ import annotations

import json
import re
from typing import Any


_PERSON_RE = re.compile(
    r"(少女|女孩|美女|女人|男子|男人|人物|角色|肖像|三视图|定妆|模特|少妇|"
    r"girl|woman|man|boy|lady|person|portrait|character|people|face|美女)",
    re.IGNORECASE,
)


def looks_like_person_prompt(prompt: str) -> bool:
    return bool(_PERSON_RE.search(prompt or ""))


def build_ideogram_caption(
    prompt: str,
    *,
    width: int,
    height: int,
    style: str = "scenery",
) -> str:
    """Build Ideogram-4 structured JSON caption (required to avoid safety false positives)."""
    text = (prompt or "").strip()
    # Strip style-suffix noise already appended for SDXL; keep core intent.
    text = re.sub(r",?\s*(photorealistic|中国风|anime style|product photography|cinematic landscape|concept art)[^,]*", "", text, flags=re.I)
    text = re.sub(r"[，,\s]{2,}", "，", text).strip("，, ").strip()
    if not text:
        text = "a cinematic scene"

    style_map: dict[str, dict[str, Any]] = {
        "scenery": {
            "aesthetics": "cinematic, atmospheric, richly detailed",
            "lighting": "natural volumetric light, soft atmosphere",
            "photo": "wide angle, deep depth of field, landscape photography",
            "medium": "photograph",
            "palette": ["#4A6B7C", "#C9B896", "#2C3E4A", "#E8E0D0", "#6B8F71"],
            "bg": "continuous environment matching the described scene with coherent depth",
        },
        "product": {
            "aesthetics": "clean, commercial, studio product shot",
            "lighting": "softbox studio lighting, gentle reflections",
            "photo": "85mm, f/8, product photography",
            "medium": "photograph",
            "palette": ["#F5F5F5", "#D0D0D0", "#222222", "#4A90E2", "#FFFFFF"],
            "bg": "clean seamless studio backdrop",
        },
        "concept": {
            "aesthetics": "concept art, design-sheet clarity, strong silhouette",
            "lighting": "clear readable studio lighting",
            "medium": "illustration",
            "art_style": "digital concept art, clean lines, presentation sheet",
            "palette": ["#F2EDE4", "#2B2B2B", "#6B8F71", "#C9A227", "#4A6B7C"],
            "bg": "plain presentation background for a design sheet",
        },
        "realistic": {
            "aesthetics": "photorealistic, natural, highly detailed",
            "lighting": "natural daylight, soft shadows",
            "photo": "50mm, f/2.8, realistic photography",
            "medium": "photograph",
            "palette": ["#E8B896", "#4A6B7C", "#2C3E4A", "#F5E6D3", "#6B8F71"],
            "bg": "realistic environment consistent with the subject",
        },
        "guofeng": {
            "aesthetics": "Chinese GuoFeng, elegant, refined",
            "lighting": "soft classical lighting",
            "medium": "illustration",
            "art_style": "Chinese digital painting, refined costume detail",
            "palette": ["#E8B896", "#2B4C7E", "#C9A227", "#F5E6D3", "#5C4033"],
            "bg": "tasteful GuoFeng environment",
        },
        "guofeng_cg": {
            "aesthetics": "3D CGI Chinese character portrait, doll-like, cinematic",
            "lighting": "soft cinematic clamshell lighting, gentle glow",
            "medium": "3D render",
            "art_style": "Unreal Engine 5 character render, octane, idealized face",
            "palette": ["#F5F5F5", "#FFFFFF", "#1A1A1A", "#C9A66B", "#E8B4B8"],
            "bg": "bokeh traditional Chinese pavilion interior",
        },
        "anime": {
            "aesthetics": "anime, clean lineart, vibrant colors",
            "lighting": "bright soft key light",
            "medium": "illustration",
            "art_style": "modern anime illustration, detailed eyes",
            "palette": ["#FFC1CC", "#87CEEB", "#FFFFFF", "#333333", "#A0E6A0"],
            "bg": "anime-style background matching the subject",
        },
    }
    sm = style_map.get(style, style_map["scenery"])

    # Aspect label
    ratio = width / max(1, height)
    if ratio >= 1.6:
        ar = "16:9"
    elif ratio <= 0.7:
        ar = "9:16"
    elif 0.9 <= ratio <= 1.1:
        ar = "1:1"
    elif ratio > 1:
        ar = "4:3"
    else:
        ar = "3:4"

    style_description: dict[str, Any] = {
        "aesthetics": sm["aesthetics"],
        "lighting": sm["lighting"],
    }
    if "photo" in sm:
        style_description["photo"] = sm["photo"]
        style_description["medium"] = sm["medium"]
    else:
        style_description["medium"] = sm["medium"]
        style_description["art_style"] = sm["art_style"]
    style_description["color_palette"] = sm["palette"]

    caption = {
        "high_level_description": text[:1200],
        "style_description": style_description,
        "compositional_deconstruction": {
            "background": sm["bg"],
            "elements": [
                {
                    "type": "obj",
                    "bbox": [120, 120, 880, 880],
                    "desc": text[:500],
                    "color_palette": sm["palette"][:5],
                }
            ],
        },
    }
    # Keep aspect as part of high_level for clarity without breaking schema
    caption["high_level_description"] = f"{caption['high_level_description']} (aspect {ar})"
    return json.dumps(caption, ensure_ascii=False, separators=(",", ":"))
