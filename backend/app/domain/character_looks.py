"""Character look-variant helpers: clothing keys, family matching, auto-clone."""
from __future__ import annotations

import re
from typing import Any


VARIANT_REASONS = frozenset({"outfit", "age", "injury", "season", "other", ""})


def normalize_clothes_key(text: str) -> str:
    s = re.sub(r"\s+", "", (text or "").strip().lower())
    # Drop common filler so「身穿黑色劲装」≈「黑色劲装」
    for prefix in ("身穿", "穿着", "穿", "着"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
    return s[:48]


def appearance_clothes(appearance: dict[str, Any] | None) -> str:
    if not isinstance(appearance, dict):
        return ""
    return normalize_clothes_key(str(appearance.get("clothing") or ""))


def look_clothes_hint(*texts: str) -> str:
    blob = "，".join(t for t in texts if (t or "").strip())
    # Prefer explicit clothing-ish spans
    for pat in (
        r"(?:身穿|穿着|穿)([^，。；;\n]{2,24})",
        r"((?:黑|白|青|蓝|红|灰|紫|绿|黄|玄|锦|布|绸|官|劲|戎|铠|甲|袍|衫|裙|裳|衣)[^，。；;\n]{0,16})",
    ):
        m = re.search(pat, blob)
        if m:
            return normalize_clothes_key(m.group(1))
    return normalize_clothes_key(blob)[:24]


def clothes_differ(a: str, b: str) -> bool:
    ka, kb = normalize_clothes_key(a), normalize_clothes_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return False
    if ka in kb or kb in ka:
        return False
    return True


def expand_character_look_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand characters[].looks into base row + variant rows (same name)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "")
        looks = row.get("looks")
        if kind not in ("character", "人物", "角色", "人物形象") and "looks" not in row:
            out.append(row)
            continue
        if not isinstance(looks, list) or not looks:
            out.append(row)
            continue
        base_meta = {k: v for k, v in row.items() if k != "looks"}
        first = True
        for look in looks:
            if not isinstance(look, dict):
                continue
            item = dict(base_meta)
            item["kind"] = "character"
            for key in ("look_zh", "desc_zh", "age_band", "refer_as", "appearance", "notes"):
                if look.get(key) not in (None, ""):
                    item[key] = look[key]
            reason = str(look.get("variant_reason") or "").strip().lower()
            if reason not in VARIANT_REASONS:
                reason = "outfit" if not first else ""
            if first and not reason:
                item.pop("variant_reason", None)
                item.pop("action", None)
                out.append(item)
                first = False
                continue
            if first:
                # First look tagged as variant — still treat as base, strip reason.
                item.pop("variant_reason", None)
                out.append(item)
                first = False
                continue
            item["action"] = "clone_variant"
            item["variant_reason"] = reason or "outfit"
            item["match_name"] = item.get("name")
            out.append(item)
            first = False
        if first:
            # looks was empty of dicts — keep original
            out.append(row)
    return out


def score_look_match(asset_clothes: str, asset_desc: str, hint: str) -> int:
    h = normalize_clothes_key(hint)
    if not h:
        return 0
    ac = normalize_clothes_key(asset_clothes)
    ad = normalize_clothes_key(asset_desc)
    score = 0
    if ac and (h in ac or ac in h):
        score += 10
    if ad and (h in ad or ac and h in ad):
        score += 4
    # Shared distinctive chars (skip ultra-common 衣/色)
    for ch in h:
        if ch in ("衣", "色", "的", "与", "和"):
            continue
        if ac and ch in ac:
            score += 1
        elif ad and ch in ad:
            score += 1
    # bigram overlap
    for i in range(0, max(0, len(h) - 1)):
        tok = h[i : i + 2]
        if tok and tok in ac:
            score += 2
        elif tok and tok in ad:
            score += 1
    return score
