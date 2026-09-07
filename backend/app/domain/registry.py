from __future__ import annotations

import re
from typing import Any


KIND_ALIASES = {
    "character": "character",
    "char": "character",
    "person": "character",
    "people": "character",
    "角色": "character",
    "人物": "character",
    "人名": "character",
    "scene": "scene",
    "location": "scene",
    "place": "scene",
    "场景": "scene",
    "地点": "scene",
    "场所": "scene",
    "prop": "prop",
    "item": "prop",
    "object": "prop",
    "物品": "prop",
    "道具": "prop",
    "信物": "prop",
}

# Generic labels that belong in refer_as / prose, never in aliases.
NON_ALIAS_TERMS = frozenset(
    {
        # refer_as vocabulary
        "少年",
        "少女",
        "老者",
        "老人",
        "老汉",
        "老头",
        "女子",
        "妇人",
        "男子",
        "男人",
        "女人",
        "青年",
        "中年",
        "孩童",
        "孩子",
        "儿童",
        "姑娘",
        "小姐",
        "公子",
        "书生",
        "侠客",
        "剑客",
        "人",
        "此人",
        "那人",
        # kinship / role words (not proper-name aliases)
        "母亲",
        "父亲",
        "妈妈",
        "爸爸",
        "娘",
        "爹",
        "母",
        "父",
        "娘亲",
        "爹爹",
        "祖父",
        "祖母",
        "爷爷",
        "奶奶",
        "外公",
        "外婆",
        "叔叔",
        "伯父",
        "舅舅",
        "姑姑",
        "姨妈",
        "阿姨",
        "哥哥",
        "姐姐",
        "弟弟",
        "妹妹",
        "兄长",
        "大哥",
        "兄弟",
        "姐妹",
        "丈夫",
        "妻子",
        "夫人",
        "娘子",
        "相公",
        "儿子",
        "女儿",
        "小孩",
        "徒弟",
        "师父",
        "师傅",
        "主人",
        "仆人",
        "侍女",
        "丫鬟",
        "船夫",
        "船工",
        "店小二",
        "路人",
        "众人",
        "旁人",
        "自己",
        "对方",
    }
)

REFER_AS_CANDIDATES = frozenset(
    {
        "少年",
        "少女",
        "老者",
        "老人",
        "女子",
        "妇人",
        "男子",
        "青年",
        "孩童",
        "姑娘",
        "公子",
        "书生",
    }
)

# Occupations / roles that belong in background, not look.
LOOK_BANNED_TERMS = frozenset(
    {
        "老船工",
        "船工",
        "船夫",
        "渔民",
        "遗孤",
        "孤儿",
        "店小二",
        "书生",
        "侠客",
        "剑客",
        "农夫",
        "渔夫",
        "商人",
        "盐商",
        "掌柜",
        "捕快",
        "将军",
        "官员",
        "知县",
        "杀手",
        "打手",
        "随从",
        "采药人",
        "老板娘",
        "少爷",
        "小姐",
        "夫人",
        "娘子",
        "相公",
        "仆人",
        "侍女",
        "丫鬟",
        "师父",
        "师傅",
        "徒弟",
    }
)

# Emotion / expression / manner words — never allowed in look_zh.
LOOK_EMOTION_WORDS = frozenset(
    {
        "温柔",
        "温和",
        "温婉",
        "和善",
        "和蔼",
        "严肃",
        "威严",
        "坚定",
        "迷茫",
        "沉稳",
        "慈祥",
        "阴鸷",
        "冷酷",
        "凶狠",
        "凶悍",
        "冷漠",
        "柔情",
        "深情",
        "含情",
        "悲悯",
        "哀伤",
        "喜悦",
        "愤怒",
        "倔强",
        "坚毅",
        "果敢",
        "柔弱",
        "狠厉",
        "平静",
        "淡然",
        "漠然",
        "悲戚",
        "忧伤",
        "欢喜",
        "狞笑",
        "假笑",
        "干笑",
        "皮笑肉不笑",
        "笑靥如花",
        "面带微笑",
        "微微一笑",
        "嫣然一笑",
        "莞尔",
        "冷笑",
        "苦笑",
        "憨笑",
        "狂笑",
        "含笑",
        "带笑",
        "笑容",
        "微笑",
        "杀意",
        "杀气",
        "戾气",
        "柔和",
        "严厉",
        "慈爱",
        "怜爱",
        "悲凉",
        "凄楚",
        "落寞",
        "惘然",
        "恍惚",
        "坚定不移",
        "从容",
        "镇定",
        "慌张",
        "紧张",
        "放松",
        "警惕",
        "戒备",
        "惊恐",
        "恐惧",
        "害怕",
        "审视",
        "精明",
        "狡黠",
        "阴险",
        "贪婪",
        "猥琐",
        "优雅",
        "雍容",  # borderline manner — user wants pure visual; 体态微胖 is enough
        "矍铄",
        "精神矍铄",
        "官威",
        "气质",
        "麻利",
        "痛苦",
        "悲苦",
        "哀愁",
        "明媚",
        "灿烂",
        "妩媚",
        "妖娆",
        "阴冷",
        "冷硬",
        "傲慢",
        "狡诈",
        "无助",
        "刚毅",
        "深邃",
        "无神",
        "精悍",
        "灵活",
        "锐利",
        "油腻",
        "热心",
        "热心肠",
        "霸道",
        "心狠",
        "孤僻",
        "厚道",
        "坚韧",
        "文弱",
    }
)

LOOK_EXPRESSION_MARKERS = (
    "神情",
    "神色",
    "神态",
    "表情",
    "面色里",
    "目光里",
    "眼神里",
    "眼里",
    "眼中",
)

LOOK_FRAGMENT_REJECT = frozenset(
    {
        "眼神",
        "目光",
        "眉眼",
        "眉目",
        "眉宇",
        "面容",
        "面色",
        "脸上",
        "面上",
        "眼睛",
        "眼里",
        "眼中",
        "带着",
        "脸上带着",
        "充满",
        "透着",
        "显得",
        "但",
        "而",
        "的",
        "地",
        "得",
        "动作",
        "双手",
        "常年劳作",
    }
)

# Clauses matching these are non-visual (emotion / action / plot).
LOOK_BANNED_PATTERNS = (
    re.compile(r"(神情|神色|神态|表情)"),
    re.compile(r"(皮笑肉不笑|笑靥如花|面带微笑|微微一笑|嫣然一笑|莞尔|冷笑|苦笑|憨笑|含笑|带笑|笑容|微笑)"),
    re.compile(r"(眉眼|眉目|眉宇|眼神|目光|双眸|眼睛|眼波).{0,8}(温柔|温和|温婉|严肃|坚定|迷茫|沉稳|慈祥|和蔼|和善|冷漠|柔情|深情|含情|阴冷|冷硬|狡诈|无助|锐利|深邃|无神|凶|狠|悲|喜|怒|厉|柔|精明)"),
    re.compile(r"(温柔|温和|温婉|严肃|坚定|迷茫|沉稳|慈祥|和善|阴冷|狡诈).{0,4}(的)?(眉眼|眉目|眼神|目光|神情|神色|表情|面容|面色)"),
    re.compile(r"(脸上|面上|满脸|一脸).{0,6}(笑|泪|怒|悲|严肃|慈祥|和善)"),
    re.compile(r"气质.{0,6}"),
    re.compile(r"(精神)?矍铄"),
    re.compile(r"手脚麻利|便于行动|常年劳作"),
    re.compile(r"(后期|文中|推断)"),
    re.compile(r"^动作|动作$|^(双手|双脚)$"),
    re.compile(r".*(转为|变得|显得|透着|带着).*(坚定|迷茫|沉稳|温柔|温和|严肃|杀意|悲|柔|怒|笑|阴冷|傲慢).*"),
    re.compile(r".*(动作|举止|步伐|步态|行事|言行).*(沉稳|稳健|轻盈|敏捷|迟缓|从容|麻利).*"),
    re.compile(r".*(寻找|寻母|寻父|复仇|逃亡|赶路|说话|对白|性格|脾气).*"),
)


def normalize_kind(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return "prop"
    if key in KIND_ALIASES:
        return KIND_ALIASES[key]
    key_cn = (raw or "").strip()
    return KIND_ALIASES.get(key_cn, KIND_ALIASES.get(key, "prop"))


def is_non_alias_term(value: str | None) -> bool:
    s = (value or "").strip()
    return (not s) or (s in NON_ALIAS_TERMS)


def _look_clause_banned(clause: str) -> bool:
    s = clause.strip()
    if not s:
        return True
    if s in LOOK_BANNED_TERMS or s in NON_ALIAS_TERMS or s in LOOK_EMOTION_WORDS:
        return True
    for term in LOOK_BANNED_TERMS:
        if term in s:
            return True
    for marker in LOOK_EXPRESSION_MARKERS:
        if marker in s:
            return True
    for word in LOOK_EMOTION_WORDS:
        if word in s:
            return True
    for pat in LOOK_BANNED_PATTERNS:
        if pat.search(s):
            return True
    return False


def _scrub_emotion_tokens(clause: str) -> str:
    scrubbed = clause
    for word in sorted(LOOK_EMOTION_WORDS | LOOK_BANNED_TERMS, key=len, reverse=True):
        if word in scrubbed:
            scrubbed = scrubbed.replace(word, "")
    scrubbed = re.sub(r"(神情|神色|神态|表情)", "", scrubbed)
    scrubbed = re.sub(r"气质.{0,8}", "", scrubbed)
    scrubbed = re.sub(r"(精神)?矍铄", "", scrubbed)
    scrubbed = re.sub(r"手脚麻利|便于行动|常年劳作", "", scrubbed)
    scrubbed = re.sub(r"(后期|文中未详述|文中提及|依[^，；;。]{0,12}推断)", "", scrubbed)
    scrubbed = re.sub(r"脸上带着|面上带着|满脸", "", scrubbed)
    scrubbed = re.sub(r"充满", "", scrubbed)
    scrubbed = re.sub(r"(手脚|动作|双手|双脚)$", "", scrubbed)
    scrubbed = re.sub(r"^(手脚|动作|双手|双脚)", "", scrubbed)
    scrubbed = re.sub(r"[的地得而且并与但却]+$", "", scrubbed.strip(" 、,，"))
    scrubbed = re.sub(r"^[的地得而且并与但却]+", "", scrubbed.strip(" 、,，"))
    return scrubbed.strip(" 、,，")

def sanitize_look_text(text: str | None) -> str:
    """Keep only visual appearance clauses for portrait generation."""
    raw = (text or "").strip()
    if not raw:
        return ""
    parts = re.split(r"[；;。！？!\n、]+|(?<=[^\d])，(?=[^\d])|,", raw)
    kept: list[str] = []
    for part in parts:
        clause = part.strip(" 、,，")
        if not clause:
            continue
        scrubbed = _scrub_emotion_tokens(clause)
        if not scrubbed or len(scrubbed) < 2:
            continue
        if scrubbed in LOOK_FRAGMENT_REJECT:
            continue
        if _look_clause_banned(scrubbed):
            continue
        # Reject near-empty fragments like "眉眼"/"眼神"/"面容" after emotion strip
        if re.fullmatch(r"(眉眼|眉目|眉宇|眼神|目光|面容|面色|眼睛|脸上|面上)", scrubbed):
            continue
        if scrubbed not in kept:
            kept.append(scrubbed)
    return "，".join(kept)


def sanitize_appearance(appearance: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (appearance or {}).items():
        if value in (None, ""):
            continue
        # Gender is a short controlled label — don't run full look scrubbers on it.
        if key == "gender":
            g = str(value).strip()
            if g in {"男", "女", "不明", "male", "female", "unknown"}:
                out["gender"] = {"male": "男", "female": "女", "unknown": "不明"}.get(g, g)
            continue
        cleaned = sanitize_look_text(str(value))
        if cleaned and cleaned not in {"无", "没有", "暂无"}:
            out[key] = cleaned
    return out


_GENDER_ZH = {"male": "男", "female": "女", "unknown": "不明"}
_AGE_TIER_ZH = {
    "child": "儿童",
    "youth": "青年",
    "adult": "中年",
    "elder": "老年",
    "unknown": "成年",
}
_TRINITY_GENDER_RE = re.compile(r"性别\s*[：:]\s*([男女不明]+)")
_TRINITY_AGE_RE = re.compile(r"年龄段\s*[：:]\s*([^，,；;。]+)")
_TRINITY_BODY_RE = re.compile(r"身材\s*[：:]\s*([^，,；;。]+)")


def _gender_zh_from_fields(
    *,
    name: str = "",
    refer_as: str = "",
    age_band: str = "",
    look: str = "",
    appearance: dict[str, Any] | None = None,
) -> str:
    app = appearance or {}
    raw = str(app.get("gender") or "").strip()
    if raw in {"男", "女", "不明"}:
        return raw
    if raw in {"male", "female", "unknown"}:
        return _GENDER_ZH[raw]
    m = _TRINITY_GENDER_RE.search(look or "")
    if m and m.group(1) in {"男", "女", "不明"}:
        return m.group(1)
    # Late import avoids circular dependency with persona helpers.
    from app.comfy_pipeline.persona import infer_gender

    g = infer_gender(name=name, refer_as=refer_as, age_band=age_band, look=look)
    return _GENDER_ZH.get(g, "不明")


def _age_band_zh_from_fields(
    *,
    name: str = "",
    refer_as: str = "",
    age_band: str = "",
    look: str = "",
) -> str:
    band = (age_band or "").strip()
    if band:
        return band
    m = _TRINITY_AGE_RE.search(look or "")
    if m:
        return m.group(1).strip()
    from app.comfy_pipeline.persona import infer_age_tier

    tier = infer_age_tier(name=name, refer_as=refer_as, age_band=age_band, look=look)
    return _AGE_TIER_ZH.get(tier, "成年")


def _body_zh_from_fields(
    *,
    look: str = "",
    appearance: dict[str, Any] | None = None,
    gender_zh: str = "不明",
    age_zh: str = "成年",
) -> str:
    app = appearance or {}
    body = sanitize_look_text(str(app.get("body") or "").strip())
    if body:
        return body
    m = _TRINITY_BODY_RE.search(look or "")
    if m:
        cand = sanitize_look_text(m.group(1).strip())
        if cand:
            return cand
    # Soft default so trinity is never empty; LLM/UI should replace with concrete build.
    if gender_zh == "女":
        return f"{age_zh}女性匀称身材"
    if gender_zh == "男":
        return f"{age_zh}男性匀称身材"
    return f"{age_zh}匀称身材"


def ensure_character_look_trinity(
    *,
    name: str = "",
    refer_as: str = "",
    age_band: str = "",
    desc_zh: str = "",
    appearance: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], str]:
    """Guarantee 性别 / 年龄段 / 身材 in character look text and appearance.

    Returns (desc_zh, appearance, age_band).
    """
    app = sanitize_appearance(dict(appearance or {}))
    look = sanitize_look_text(desc_zh or "")
    gender_zh = _gender_zh_from_fields(
        name=name, refer_as=refer_as, age_band=age_band, look=look, appearance=app
    )
    age_zh = _age_band_zh_from_fields(
        name=name, refer_as=refer_as, age_band=age_band, look=look
    )
    body_zh = _body_zh_from_fields(
        look=look, appearance=app, gender_zh=gender_zh, age_zh=age_zh
    )
    app["gender"] = gender_zh
    app["body"] = body_zh

    # Strip old trinity clauses then re-prefix so order is stable.
    stripped = look
    stripped = _TRINITY_GENDER_RE.sub("", stripped)
    stripped = _TRINITY_AGE_RE.sub("", stripped)
    stripped = _TRINITY_BODY_RE.sub("", stripped)
    stripped = re.sub(r"[，,]{2,}", "，", stripped).strip("，,；; ")
    # Drop duplicate bare body clause if identical to body_zh
    parts = [p for p in re.split(r"[，,]", stripped) if p.strip() and p.strip() != body_zh]
    rest = "，".join(parts)
    prefix = f"性别：{gender_zh}，年龄段：{age_zh}，身材：{body_zh}"
    new_desc = prefix if not rest else f"{prefix}，{rest}"
    return new_desc, app, age_zh


def character_look_trinity_missing(asset: dict[str, Any]) -> list[str]:
    """Return missing required look fields among 性别/年龄段/身材."""
    miss: list[str] = []
    app = asset.get("appearance") or {}
    look = (asset.get("desc_zh") or asset.get("look_zh") or "").strip()
    gender = str(app.get("gender") or "").strip()
    if gender not in {"男", "女", "不明"} and not _TRINITY_GENDER_RE.search(look):
        miss.append("性别")
    age = (asset.get("age_band") or "").strip()
    if not age and not _TRINITY_AGE_RE.search(look):
        miss.append("年龄段")
    body = str(app.get("body") or "").strip()
    if not body and not _TRINITY_BODY_RE.search(look):
        miss.append("身材")
    return miss


def sanitize_aliases(
    aliases: list[Any] | None,
    *,
    name: str = "",
    refer_as: str = "",
) -> list[str]:
    """Keep only proper-name aliases; drop refer_as labels and kinship roles."""
    out: list[str] = []
    name = (name or "").strip()
    refer_as = (refer_as or "").strip()
    for raw in aliases or []:
        s = str(raw or "").strip()
        if not s or s == name or s == refer_as:
            continue
        if is_non_alias_term(s):
            continue
        if s not in out:
            out.append(s)
    return out


def sanitize_character_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize character name/aliases/refer_as after LLM output."""
    out = dict(row)
    name = (out.get("name") or "").strip()
    refer_as = (out.get("refer_as") or "").strip()
    aliases_in = list(out.get("aliases") or [])

    if not refer_as:
        for a in aliases_in:
            s = str(a or "").strip()
            if s in REFER_AS_CANDIDATES:
                refer_as = s
                break
    if is_non_alias_term(name) and name in REFER_AS_CANDIDATES and not refer_as:
        refer_as = name

    out["name"] = name
    out["refer_as"] = refer_as or (out.get("refer_as") or "")
    out["aliases"] = sanitize_aliases(aliases_in, name=name, refer_as=out["refer_as"])
    if "look_zh" in out or "desc_zh" in out or "notes" in out:
        if out.get("look_zh"):
            out["look_zh"] = sanitize_look_text(out.get("look_zh"))
        if out.get("desc_zh"):
            out["desc_zh"] = sanitize_look_text(out.get("desc_zh"))
    if out.get("appearance") is not None:
        out["appearance"] = sanitize_appearance(out.get("appearance"))
    # Mandatory trinity: 性别 / 年龄段 / 身材
    desc_src = out.get("look_zh") or out.get("desc_zh") or ""
    new_desc, new_app, new_age = ensure_character_look_trinity(
        name=out.get("name") or "",
        refer_as=out.get("refer_as") or "",
        age_band=out.get("age_band") or "",
        desc_zh=desc_src,
        appearance=out.get("appearance") or {},
    )
    out["age_band"] = new_age
    out["appearance"] = new_app
    if "look_zh" in out:
        out["look_zh"] = new_desc
    if "desc_zh" in out or "look_zh" not in out:
        out["desc_zh"] = new_desc
    return out


def merge_registry_entry(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    kind = normalize_kind(incoming.get("kind") or existing.get("kind"))
    merged["kind"] = kind
    if incoming.get("name"):
        merged["name"] = str(incoming["name"]).strip()
    aliases = list(existing.get("aliases") or [])
    aliases.extend(incoming.get("aliases") or [])
    if (
        incoming.get("name")
        and incoming["name"] != existing.get("name")
        and not is_non_alias_term(incoming["name"])
    ):
        aliases.append(incoming["name"])
    if incoming.get("refer_as") and not (existing.get("refer_as") or "").strip():
        merged["refer_as"] = incoming["refer_as"]
    elif incoming.get("refer_as"):
        merged["refer_as"] = incoming["refer_as"]
    if incoming.get("age_band") and not (existing.get("age_band") or "").strip():
        merged["age_band"] = incoming["age_band"]
    elif incoming.get("age_band"):
        merged["age_band"] = incoming["age_band"]

    appearance = dict(existing.get("appearance") or {})
    for key, value in (incoming.get("appearance") or {}).items():
        if value in (None, ""):
            continue
        appearance[key] = value
    merged["appearance"] = appearance

    # background_zh = identity/backstory (user-facing only)
    bg = (existing.get("background_zh") or "").strip()
    add_bg = (incoming.get("background_zh") or incoming.get("background") or incoming.get("identity") or "").strip()
    if add_bg:
        if not bg:
            merged["background_zh"] = add_bg
        elif add_bg not in bg:
            merged["background_zh"] = f"{bg}；{add_bg}"
        else:
            merged["background_zh"] = bg

    # desc_zh = look only (face/body/clothing) for image generation
    desc_zh = (existing.get("desc_zh") or "").strip()
    add_zh = (
        incoming.get("look_zh")
        or incoming.get("desc_zh")
        or incoming.get("notes")
        or ""
    ).strip()
    # If model stuffed both into notes, prefer look_zh/desc_zh; never copy background into look
    if add_zh and add_bg and add_zh == add_bg:
        add_zh = ""
    add_zh = sanitize_look_text(add_zh)
    if add_zh:
        if not desc_zh:
            merged["desc_zh"] = add_zh
        elif add_zh not in desc_zh:
            merged["desc_zh"] = sanitize_look_text(f"{desc_zh}；{add_zh}")
        else:
            merged["desc_zh"] = sanitize_look_text(desc_zh)
    elif desc_zh:
        merged["desc_zh"] = sanitize_look_text(desc_zh)
    merged["appearance"] = sanitize_appearance(merged.get("appearance") or appearance)
    desc_en = (existing.get("desc_en") or "").strip()
    add_en = (incoming.get("desc_en") or incoming.get("look_en") or "").strip()
    if add_en and not desc_en:
        merged["desc_en"] = add_en
    elif add_en and add_en not in desc_en:
        merged["desc_en"] = f"{desc_en}; {add_en}"

    if merged["kind"] == "character":
        cleaned = sanitize_character_fields({**merged, "aliases": aliases})
        merged["aliases"] = cleaned["aliases"]
        merged["refer_as"] = cleaned["refer_as"] or merged.get("refer_as") or "人"
        merged["age_band"] = cleaned.get("age_band") or merged.get("age_band") or ""
        merged["appearance"] = cleaned.get("appearance") or merged.get("appearance") or {}
        merged["desc_zh"] = cleaned.get("desc_zh") or merged.get("desc_zh") or ""
        if cleaned.get("look_zh"):
            merged["look_zh"] = cleaned["look_zh"]
    else:
        merged["aliases"] = sanitize_aliases(aliases, name=merged.get("name") or "")
    return merged


def look_text(asset: dict[str, Any]) -> str:
    """Visual look string used for portrait generation (never includes background)."""
    desc, app, _age = ensure_character_look_trinity(
        name=str(asset.get("name") or ""),
        refer_as=str(asset.get("refer_as") or ""),
        age_band=str(asset.get("age_band") or ""),
        desc_zh=str(asset.get("desc_zh") or asset.get("look_zh") or ""),
        appearance=asset.get("appearance") or {},
    )
    parts: list[str] = [desc] if desc else []
    for key in ("face", "hair", "eyes", "skin", "body", "posture", "marks", "clothing", "accessories", "condition"):
        val = (app.get(key) or "").strip()
        if val and val not in desc:
            parts.append(val)
    return "，".join(parts)


def _entry_incomplete(asset: dict[str, Any]) -> dict[str, Any] | None:
    kind = normalize_kind(asset.get("kind"))
    name = (asset.get("name") or "").strip()
    if not name:
        return {"name": name or "?", "kind": kind, "reason": "缺少名称"}
    if kind == "character":
        miss = character_look_trinity_missing(asset)
        if miss:
            return {"name": name, "kind": kind, "reason": "缺少必带项：" + "、".join(miss)}
        if not look_text(asset):
            return {"name": name, "kind": kind, "reason": "缺少样貌/身材/服饰描述"}
        return None
    desc = (asset.get("desc_zh") or asset.get("notes") or "").strip()
    if kind in ("scene", "prop") and not desc:
        return {"name": name, "kind": kind, "reason": "缺少可视化描述"}
    return None


def registry_completeness(assets: list[dict[str, Any]]) -> dict[str, Any]:
    incomplete = []
    for asset in assets:
        miss = _entry_incomplete(asset)
        if miss:
            incomplete.append(miss)
    counts = {"character": 0, "scene": 0, "prop": 0}
    for asset in assets:
        k = normalize_kind(asset.get("kind"))
        counts[k] = counts.get(k, 0) + 1
    return {
        "complete": len(incomplete) == 0 and counts["character"] > 0,
        "incomplete": incomplete,
        "counts": counts,
    }


def is_registry_complete(assets: list[dict[str, Any]]) -> bool:
    return bool(registry_completeness(assets)["complete"])


def _find_index(assets: list[dict[str, Any]], name: str, kind: str) -> int:
    needle = name.strip()
    for i, asset in enumerate(assets):
        if normalize_kind(asset.get("kind")) != kind:
            continue
        names = [asset.get("name"), *(asset.get("aliases") or [])]
        if needle in {str(n).strip() for n in names if n}:
            return i
    return -1


def apply_registry_delta(
    assets: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> tuple[int, int]:
    created = 0
    updated = 0
    for row in rows:
        kind = normalize_kind(row.get("kind"))
        name = (row.get("name") or "").strip()
        if not name:
            continue
        # Generic role-only rows (母亲/少年) are not registry people
        if kind == "character" and is_non_alias_term(name) and not (row.get("aliases") or []):
            continue
        payload = {
            "kind": kind,
            "name": name,
            "aliases": row.get("aliases") or [],
            "refer_as": row.get("refer_as") or ("人" if kind == "character" else ""),
            "age_band": row.get("age_band") or "",
            "appearance": row.get("appearance") or {},
            "background_zh": row.get("background_zh") or row.get("background") or row.get("identity") or "",
            "desc_zh": row.get("look_zh") or row.get("desc_zh") or row.get("notes") or "",
            "desc_en": row.get("desc_en") or row.get("look_en") or "",
        }
        if kind == "character":
            payload = sanitize_character_fields(payload)
            # notes without look_zh often mixed bio+look — prefer explicit look_zh; keep notes only if no look_zh/desc_zh
            if row.get("look_zh") or row.get("desc_zh"):
                payload["desc_zh"] = (row.get("look_zh") or row.get("desc_zh") or "").strip()
            elif row.get("notes") and not payload.get("background_zh"):
                # ambiguous notes → treat as look (generation-critical)
                payload["desc_zh"] = (row.get("notes") or "").strip()
            if is_non_alias_term(payload["name"]) and not payload["aliases"]:
                continue
            # Never let background bleed into look when both provided equal
            if payload.get("background_zh") and payload.get("desc_zh") == payload.get("background_zh"):
                payload["desc_zh"] = look_text({"appearance": payload.get("appearance") or {}})
        idx = _find_index(assets, name, kind)
        if idx < 0 and kind == "character":
            idx = _find_index(assets, payload["name"], kind)
        if idx < 0:
            assets.append(payload)
            created += 1
        else:
            assets[idx] = merge_registry_entry(assets[idx], payload)
            updated += 1
    return created, updated
