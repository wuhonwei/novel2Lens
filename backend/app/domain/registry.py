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
        "遗孤",
        "孤儿",
        "店小二",
        "书生",
        "侠客",
        "剑客",
        "农夫",
        "渔夫",
        "商人",
        "掌柜",
        "捕快",
        "将军",
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

# Clauses matching these are non-visual (emotion / action / plot).
LOOK_BANNED_PATTERNS = (
    re.compile(r".*(迷茫|坚定|沉稳|果敢|柔弱|狠厉|冷漠|温柔|倔强|坚毅|哀伤|悲悯|愤怒|喜悦).*(转|变|为|成|而|地|的).*"),
    re.compile(r".*(眼神|目光|神情|神色|神态).*(迷茫|坚定|沉稳|温柔|冷|狠|怒|喜|哀|惊).*"),
    re.compile(r".*(转为|变得|显得|透着|带着).*(坚定|迷茫|沉稳|温柔|杀意|悲).*"),
    re.compile(r"(笑靥如花|面带微笑|微微一笑|嫣然一笑|莞尔|冷笑|苦笑)"),
    re.compile(r".*(动作|举止|步伐|步态|行事).*(沉稳|稳健|轻盈|敏捷|迟缓).*"),
    re.compile(r".*(寻找|寻母|寻父|复仇|逃亡|赶路|说话|对白|性格).*"),
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
    if s in LOOK_BANNED_TERMS or s in NON_ALIAS_TERMS:
        return True
    for term in LOOK_BANNED_TERMS:
        if term == s or (len(term) >= 2 and term in s and len(s) <= len(term) + 2):
            return True
    for pat in LOOK_BANNED_PATTERNS:
        if pat.search(s):
            return True
    return False


def sanitize_look_text(text: str | None) -> str:
    """Keep only visual appearance clauses for portrait generation."""
    raw = (text or "").strip()
    if not raw:
        return ""
    # Split on common Chinese / English separators while keeping content pieces
    parts = re.split(r"[；;。！？!\n]+|(?<=[^\d])，(?=[^\d])|,", raw)
    kept: list[str] = []
    for part in parts:
        clause = part.strip(" 、,，")
        if not clause or _look_clause_banned(clause):
            continue
        # Drop bare occupation words glued with commas already split
        if clause in LOOK_BANNED_TERMS:
            continue
        if clause not in kept:
            kept.append(clause)
    return "，".join(kept)


def sanitize_appearance(appearance: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (appearance or {}).items():
        if value in (None, ""):
            continue
        cleaned = sanitize_look_text(str(value))
        if cleaned:
            out[key] = cleaned
    return out


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
        look = out.get("look_zh") or out.get("desc_zh") or ""
        # notes may be mixed; only sanitize explicit look fields here
        if out.get("look_zh"):
            out["look_zh"] = sanitize_look_text(out.get("look_zh"))
        if out.get("desc_zh"):
            out["desc_zh"] = sanitize_look_text(out.get("desc_zh"))
    if out.get("appearance") is not None:
        out["appearance"] = sanitize_appearance(out.get("appearance"))
    return out


def merge_registry_entry(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    kind = normalize_kind(incoming.get("kind") or existing.get("kind"))
    if kind == "character":
        incoming = sanitize_character_fields(incoming)
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
    else:
        merged["aliases"] = sanitize_aliases(aliases, name=merged.get("name") or "")
    return merged


def look_text(asset: dict[str, Any]) -> str:
    """Visual look string used for portrait generation (never includes background)."""
    parts: list[str] = []
    desc = sanitize_look_text(asset.get("desc_zh") or asset.get("look_zh") or "")
    if desc:
        parts.append(desc)
    appearance = sanitize_appearance(asset.get("appearance") or {})
    for key in ("face", "hair", "eyes", "skin", "body", "posture", "marks", "clothing", "accessories", "condition"):
        val = (appearance.get(key) or "").strip()
        if val and val not in desc:
            parts.append(val)
    return "，".join(parts)


def _entry_incomplete(asset: dict[str, Any]) -> dict[str, Any] | None:
    kind = normalize_kind(asset.get("kind"))
    name = (asset.get("name") or "").strip()
    if not name:
        return {"name": name or "?", "kind": kind, "reason": "缺少名称"}
    if kind == "character":
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
