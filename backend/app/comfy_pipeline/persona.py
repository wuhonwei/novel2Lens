"""Infer character gender / age for T2I prompt locks."""
from __future__ import annotations

import re
from typing import Literal

Gender = Literal["male", "female", "unknown"]
AgeTier = Literal["child", "youth", "adult", "elder", "unknown"]

_MALE_RE = re.compile(
    r"(男子|男人|男性|男孩|少年|公子|少爷|书生|侠客|汉子|老头|老汉|大爷|爷爷|伯父|"
    r"叔父|父亲|爹|哥|弟|兄|丈夫|女婿|武生|小厮|捕快|衙役|将军|王爷|"
    r"\bman\b|\bmale\b|\bboy\b|\byouth\b)",
    re.IGNORECASE,
)
_FEMALE_RE = re.compile(
    r"(女子|女人|女性|女孩|少女|姑娘|小姐|夫人|娘子|婆婆|老太太|奶奶|姥姥|"
    r"母亲|娘|妈|姐|妹|妻|妾|丫鬟|侍女|宫女|妃|"
    r"\bwoman\b|\bfemale\b|\bgirl\b|\blady\b)",
    re.IGNORECASE,
)
_ELDER_RE = re.compile(
    r"(婆婆|老太太|老太|奶奶|姥姥|爷爷|大爷|老头|老汉|老妇|老者|苍老|年迈|"
    r"白发|银发|皱纹|花甲|古稀|耄耋|六[十0-9]|七[十0-9]|八[十0-9]|九[十0-9]|"
    r"6[0-9]|7[0-9]|8[0-9]|9[0-9]|elder|elderly|old\s*woman|old\s*man)",
    re.IGNORECASE,
)
_CHILD_RE = re.compile(r"(孩童|幼童|儿童|小儿|女童|男童|娃娃|\bchild\b|\bkid\b)", re.IGNORECASE)
_YOUTH_RE = re.compile(
    r"(少年|少女|青年|十七|十八|十九|二十|1[7-9]|2[0-5]岁|teen|young\s*adult)",
    re.IGNORECASE,
)


def infer_gender(*, name: str = "", refer_as: str = "", age_band: str = "", look: str = "") -> Gender:
    blob = f"{name} {refer_as} {age_band} {look}"
    male = bool(_MALE_RE.search(blob))
    female = bool(_FEMALE_RE.search(blob))
    if male and not female:
        return "male"
    if female and not male:
        return "female"
    # name heuristics: 婆/娘/姐 often female; 汉/哥 often male
    if re.search(r"(婆|娘|姐|妹|妃|鬟)", name or ""):
        return "female"
    if re.search(r"(汉|哥|爷|伯|叔|公(?!主))", name or ""):
        return "male"
    if male and female:
        # prefer refer_as / age_band over look prose noise
        ref = f"{refer_as} {age_band} {name}"
        if _MALE_RE.search(ref) and not _FEMALE_RE.search(ref):
            return "male"
        if _FEMALE_RE.search(ref) and not _MALE_RE.search(ref):
            return "female"
    return "unknown"


def infer_age_tier(*, name: str = "", refer_as: str = "", age_band: str = "", look: str = "") -> AgeTier:
    blob = f"{name} {refer_as} {age_band} {look}"
    if _ELDER_RE.search(blob):
        return "elder"
    if _CHILD_RE.search(blob):
        return "child"
    if _YOUTH_RE.search(blob):
        return "youth"
    # numeric age_band like "60岁左右"
    m = re.search(r"(\d{1,3})\s*岁", blob)
    if m:
        n = int(m.group(1))
        if n >= 55:
            return "elder"
        if n <= 12:
            return "child"
        if n <= 25:
            return "youth"
        return "adult"
    return "unknown"


def identity_lock_zh(*, gender: Gender, age_tier: AgeTier, refer_as: str = "", age_band: str = "") -> str:
    """Hard Chinese identity tokens prepended to T2I prompts."""
    parts: list[str] = []
    if gender == "male":
        if age_tier == "elder":
            parts.append("老年男性，苍老男子，明显皱纹，花白或灰白头发")
        elif age_tier == "youth":
            parts.append("年轻男性，少年男子，男性五官")
        elif age_tier == "child":
            parts.append("男童，小男孩")
        else:
            parts.append("男性，男子，男性五官与体态")
    elif gender == "female":
        if age_tier == "elder":
            parts.append("老年女性，苍老妇人，明显皱纹，花白头发，不可年轻化")
        elif age_tier == "youth":
            parts.append("年轻女性，少女")
        elif age_tier == "child":
            parts.append("女童，小女孩")
        else:
            parts.append("女性，女子")
    if (age_band or "").strip():
        parts.append(f"年龄感：{age_band.strip()}")
    if (refer_as or "").strip() and refer_as.strip() not in ("人", "人物"):
        parts.append(f"身份称谓：{refer_as.strip()}")
    return "，".join(parts)


def identity_lock_en(*, gender: Gender, age_tier: AgeTier) -> str:
    if gender == "male":
        if age_tier == "elder":
            return "elderly Chinese man, old male, wrinkled aged face, gray or white hair, masculine features"
        if age_tier == "youth":
            return "young Chinese man, teenage boy, male face, masculine features, 1boy"
        if age_tier == "child":
            return "Chinese boy child, male child, 1boy"
        return "Chinese man, adult male, masculine face and body, 1boy, male"
    if gender == "female":
        if age_tier == "elder":
            return (
                "elderly Chinese woman, old grandmother, deeply wrinkled aged face, "
                "gray-white hair, aged skin texture, visibly old, not young"
            )
        if age_tier == "youth":
            return "young Chinese woman, teenage girl, 1girl"
        if age_tier == "child":
            return "Chinese girl child, 1girl"
        return "Chinese woman, adult female, 1girl"
    return ""


def identity_negative(*, gender: Gender, age_tier: AgeTier) -> str:
    parts: list[str] = []
    if gender == "male":
        parts.extend(
            [
                "woman",
                "girl",
                "1girl",
                "female",
                "feminine face",
                "lipstick",
                "breasts",
                "cleavage",
                "女性",
                "女人",
                "少女",
                "女孩",
            ]
        )
    elif gender == "female":
        parts.extend(["man", "boy", "1boy", "male", "男性", "男人", "少年男子"])
    if age_tier == "elder":
        parts.extend(
            [
                "young",
                "teenager",
                "teen",
                "youthful",
                "smooth porcelain skin",
                "doll-like face",
                "beautiful young woman",
                "beautiful young man",
                "idol face",
                "baby face",
                "年轻",
                "少女",
                "少妇",
                "无皱纹",
            ]
        )
    return ", ".join(parts)
