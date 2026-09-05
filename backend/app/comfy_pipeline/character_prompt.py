from __future__ import annotations

import re


_FULLBODY_RE = re.compile(
    r"(全身|从头到脚|头到脚|可见鞋子|鞋子可见|露出鞋子|full\s*-?\s*body|head\s*to\s*toe|shoes?\s*visible)",
    re.IGNORECASE,
)
_CLOSEUP_RE = re.compile(
    r"(特写|半身|近景|头像|胸像|肖像|上半身|close\s*-?\s*up|bust\s*shot|head\s*shot|portrait|shoulder\s*up)",
    re.IGNORECASE,
)
_FRONT_RE = re.compile(r"(正面|正对|front\s*view|facing\s*(the\s*)?camera|looking\s*at\s*viewer)", re.IGNORECASE)
_WHITE_HAIR_RE = re.compile(r"(白发|银发|白色头发|雪白头发|white\s*hair|silver\s*hair)", re.IGNORECASE)
_PERSON_RE = re.compile(
    r"(少女|女孩|美女|女人|女子|男子|男人|人物|角色|模特|girl|woman|man|lady|person|portrait|character)",
    re.IGNORECASE,
)
_NO_BG_RE = re.compile(
    r"(无背景|透明背景|白底|纯白背景|抠图|isolated|transparent\s*background|pure\s*white\s*background|plain\s*white\s*background|white\s*backdrop)",
    re.IGNORECASE,
)

NO_BG_EXTRAS = [
    "isolated subject on pure white background",
    "plain pure white backdrop",
    "seamless white studio background",
    "no scenery",
    "no environment",
    "cutout character sheet",
    "even studio lighting",
]

NO_BG_NEGATIVE = [
    "palace",
    "courtyard",
    "room interior",
    "landscape",
    "scenery",
    "busy background",
    "gradient background",
    "bokeh background",
    "wooden pillars",
    "architecture",
    "trees",
    "floor pattern",
    "shadowy backdrop",
]

# strip environment phrases injected by style recipes
_BG_ENV_DROP = {
    "standing in a traditional Chinese palace courtyard",
    "blurred traditional Chinese palace interior",
    "shallow depth of field",
}


def is_no_background_prompt(prompt: str, *, flag: bool = False) -> bool:
    if flag:
        return True
    return bool(_NO_BG_RE.search(prompt or ""))


def apply_no_background(prompt: str, extras: list[str]) -> tuple[str, list[str]]:
    """Force white studio isolation; remove conflicting environment tokens."""
    text = (prompt or "").strip()
    text = re.sub(
        r"(虚化古风宫殿背景|古风宫殿背景|宫殿背景|宫殿庭院|palace courtyard|bokeh background)",
        "纯白背景",
        text,
        flags=re.IGNORECASE,
    )
    if "无背景" not in text and "白底" not in text and "纯白" not in text:
        text = f"{text}，无背景，纯白底"
    cleaned = [e for e in extras if e not in _BG_ENV_DROP]
    cleaned.extend(NO_BG_EXTRAS)
    return text, cleaned

# 半身：可细写脸部
GUOFENG_CG_LOOK = [
    "solo, single person, one woman only",
    "beautiful young Chinese woman",
    "delicate oval face",
    "slightly enlarged doll-like eyes",
    "innocent melancholic expression",
    "lips slightly parted",
    "smooth porcelain doll skin",
    "soft peach blush",
    "jet black intricate traditional Chinese updo",
    "pink floral hairpins",
    "long hanging pink pearl buyao tassels",
    "long dangling pink bead earrings",
    "pale pink and white hanfu with embroidered collar",
    "soft front cinematic lighting",
    "gentle skin glow",
    "shallow depth of field",
    "blurred traditional Chinese palace interior",
    "stylized 3D game character render",
    "donghua CGI style",
    "Unreal Engine 5 character trailer still",
    "octane render",
    "idealized beauty, not photoreal documentary",
    "looking at viewer",
]

# 全身：缩短脸部词，避免 SDXL 被拉成胸像
GUOFENG_CG_LOOK_FULLBODY = [
    "solo, single person, one young Chinese woman only",
    "pink and white hanfu with cross collar",
    "black traditional updo with pink floral hairpins and hanging buyao beads",
    "long pink bead earrings",
    "standing in a traditional Chinese palace courtyard",
    "soft cinematic lighting",
    "stylized 3D CGI donghua, Unreal Engine 5, octane render",
    "looking at viewer",
]

GUOFENG_CG_CLOSEUP_SHOT = [
    "close-up portrait",
    "head and shoulders framing",
    "face in sharp focus",
]

GUOFENG_CG_FULLBODY_SHOT = [
    "full body shot",
    "complete full body",
    "head to toe visible",
    "feet and shoes fully visible at the bottom of the image",
    "wearing clear visible shoes or boots",
    "standing pose",
    "character centered in frame",
    "uncropped full figure",
    "long shot of whole figure",
    "not a close-up",
    "not a bust shot",
    "not cropped at knees",
]

FULLBODY_EXTRAS = [
    "full body shot",
    "complete full body",
    "head to toe visible",
    "feet and shoes fully visible at the bottom of the image",
    "wearing clear visible shoes or boots",
    "feet planted on the ground",
    "extra empty margin below the feet",
    "subject occupies about 70 percent of frame height",
    "standing far enough from camera to show whole figure",
    "ample headroom and footroom",
    "character centered in frame",
    "uncropped full figure",
    "long shot",
    "not a close-up",
    "not a cowboy shot",
    "not cropped at knees",
]

FULLBODY_NEGATIVE = [
    "cropped",
    "upper body",
    "close-up",
    "bust shot",
    "portrait crop",
    "headshot",
    "cowboy shot",
    "medium shot",
    "knees cropped",
    "cut off at thighs",
    "missing feet",
    "cut off feet",
    "out of frame feet",
    "shoes out of frame",
    "sitting cropped",
    "waist up",
    "hips crop",
    "head and shoulders only",
]

CLOSEUP_NEGATIVE = [
    "full body",
    "wide shot",
    "long shot",
    "tiny face",
    "distant subject",
    "feet in frame",
    "shoes visible",
]

GUOFENG_CG_QUALITY_NEGATIVE = [
    "multiple people",
    "two girls",
    "twins",
    "crowd",
    "flat 2d illustration",
    "sketch",
    "lineart only",
    "low poly",
    "harsh plastic skin",
    "deformed eyes",
    "asymmetrical face",
    "extra fingers",
    "watermark",
    "text",
    "raw photo",
    "smartphone snapshot",
    "wrinkled skin",
    "overly realistic pores",
    "mustache",
    "beard",
]


def is_fullbody_prompt(prompt: str) -> bool:
    """全身优先：即使用户写了「全身特写」，也按全身处理。"""
    return bool(_FULLBODY_RE.search(prompt or ""))


def ensure_fullbody_shoes_hint(prompt: str) -> str:
    text = (prompt or "").strip()
    if not is_fullbody_prompt(text):
        return text
    if re.search(r"(可见鞋子|鞋子|boots?|shoes?|feet)", text, re.IGNORECASE):
        return text
    return f"{text}，可见鞋子"

def is_closeup_prompt(prompt: str) -> bool:
    """半身/特写；若同时写了全身，不算特写。"""
    if is_fullbody_prompt(prompt):
        return False
    return bool(_CLOSEUP_RE.search(prompt or ""))


def is_person_prompt(prompt: str) -> bool:
    return bool(_PERSON_RE.search(prompt or ""))


def prefer_portrait_aspect(prompt: str, aspect: str, style: str = "") -> str:
    if is_fullbody_prompt(prompt):
        return "9:16"
    if style == "guofeng_cg" or is_closeup_prompt(prompt):
        if aspect in {"16:9", "4:3"}:
            return "3:4"
        return aspect if aspect in {"1:1", "3:4", "9:16"} else "3:4"
    if is_person_prompt(prompt) and _FRONT_RE.search(prompt or ""):
        if aspect in {"16:9", "4:3"}:
            return "3:4"
    return aspect


def _normalize_fullbody_text(text: str) -> str:
    text = re.sub(r"全身特写", "全身照，从头到脚完整入镜", text)
    text = re.sub(r"(?<![全半])特写", "细节清晰", text)
    text = re.sub(r"\bclose[\s-]*up\b", "detailed", text, flags=re.IGNORECASE)
    # 浅景深/虚化会强烈偏向半身肖像
    text = re.sub(r"浅景深|大光圈虚化|背景虚化", "环境清晰可见", text)
    return text


def _hair_extras(text: str) -> list[str]:
    if not _WHITE_HAIR_RE.search(text):
        return []
    return [
        "pure white hair",
        "silver-white long hair",
        "white colored hair",
        "snow white hair strands",
    ]


def enrich_character_prompt(
    prompt: str,
    style: str,
    *,
    no_background: bool = False,
    gender: str = "unknown",
    age_tier: str = "unknown",
) -> str:
    """Shot type follows user prompt; 全身优先于特写. Gender must not default to woman."""
    raw = (prompt or "").strip()
    fullbody = is_fullbody_prompt(raw)
    want_nobg = is_no_background_prompt(raw, flag=no_background)
    text = _normalize_fullbody_text(raw) if fullbody else raw
    extras: list[str] = []

    if gender == "male":
        solo = "solo, single person, one man only"
        subject = "man"
        anime_token = "1boy"
    elif gender == "female":
        solo = "solo, single person, one woman only"
        subject = "woman"
        anime_token = "1girl"
    else:
        solo = "solo, single person, one character only"
        subject = "person"
        anime_token = ""

    if style == "guofeng_cg":
        # Avoid baked-in "beautiful young Chinese woman" recipe — identity comes from prompt.
        if fullbody:
            extras.extend([solo, "Chinese historical costume"])
            extras.extend(GUOFENG_CG_FULLBODY_SHOT)
            extras.extend(_hair_extras(raw))
            if want_nobg:
                text, extras = apply_no_background(text, extras)
            return (
                f"full body standing shot of a {subject}, head to toe, feet and shoes visible, "
                f"{text}, " + ", ".join(extras) + ", FULL BODY, entire figure in frame, feet visible"
            )
        extras.extend([solo, "Chinese historical costume", "detailed face"])
        extras.extend(GUOFENG_CG_CLOSEUP_SHOT)
        extras.extend(_hair_extras(raw))
        if want_nobg:
            text, extras = apply_no_background(text, extras)
        return f"{text}, " + ", ".join(extras) + ", CLOSE-UP, head and shoulders only"

    if is_person_prompt(text):
        extras.append(solo)

    if fullbody:
        extras.extend(FULLBODY_EXTRAS)
        extras.extend(_hair_extras(raw))
        if _FRONT_RE.search(raw):
            extras.extend(["front view", "facing camera", "looking at viewer", "symmetrical standing pose"])
        if style == "anime" and anime_token:
            extras.extend([anime_token, "full body"])
        if style == "guofeng":
            extras.append("detailed face, elegant clothing")
        if want_nobg:
            text, extras = apply_no_background(text, extras)
        return (
            f"full body standing shot of a {subject}, head to toe, feet and shoes visible, "
            f"{text}, " + ", ".join(extras) + ", FULL BODY, entire figure in frame, feet visible"
        )

    if is_closeup_prompt(text):
        extras.extend(
            [
                "close-up portrait",
                "head and shoulders",
                "face in sharp focus",
                "shallow depth of field",
            ]
        )

    if _FRONT_RE.search(text):
        extras.extend(["front view", "facing camera", "looking at viewer"])

    extras.extend(_hair_extras(raw))

    if style == "anime" and anime_token:
        extras.append(anime_token)
    if style == "guofeng":
        extras.append("detailed face, elegant clothing")

    if want_nobg:
        text, extras = apply_no_background(text, extras)

    if not extras:
        return text
    return f"{text}, " + ", ".join(extras)


def enrich_character_negative(
    prompt: str,
    negative: str | None,
    style: str = "",
    *,
    no_background: bool = False,
    gender: str = "unknown",
    age_tier: str = "unknown",
) -> str:
    base = (negative or "").strip()
    extra: list[str] = ["multiple people", "twins", "crowd"]
    if gender == "male":
        extra.extend(["two girls", "woman", "1girl"])
    elif gender == "female":
        extra.extend(["two boys", "man", "1boy"])
    else:
        extra.extend(["two girls", "two boys"])

    if is_fullbody_prompt(prompt or ""):
        extra.extend(FULLBODY_NEGATIVE)
    elif style == "guofeng_cg" or is_closeup_prompt(prompt or ""):
        extra.extend(CLOSEUP_NEGATIVE)

    if style == "guofeng_cg" and gender != "male" and age_tier != "elder":
        extra.extend(GUOFENG_CG_QUALITY_NEGATIVE)

    if is_no_background_prompt(prompt or "", flag=no_background):
        extra.extend(NO_BG_NEGATIVE)

    if _WHITE_HAIR_RE.search(prompt or ""):
        extra.extend(["black hair", "dark hair", "brown hair", "brunette", "black-haired"])

    seen: set[str] = set()
    ordered: list[str] = []
    for part in (base.split(",") if base else []) + extra:
        p = part.strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            ordered.append(p)
    return ", ".join(ordered)
