"""Salvage spoken lines from storyboard source excerpts into H3 dialogue."""
from __future__ import annotations

import re
from typing import Any

_QUOTE_RE = re.compile(r"[「『“\"]([^」』”\"]{2,160})[」』”\"]")

_SKIP_QUOTES = frozenset(
    {
        "忠守",
        "苏",
        "苏晚卿",
        "林砚之",
        "陈守义",
        "赵万山",
    }
)

_SPEECH_VERB = re.compile(r"(说|道|问|喊|叫|嚷|念|开口|轻声|哽咽)")
_OFFSCREEN_SPEAKER = re.compile(
    r"(老板娘|随从|渔民|衙役|县令|众人|有人|百姓|旁人|差役|官兵)"
)
_ADDRESS_VERB = re.compile(r"(盯着|对着|面向|朝着|望着|护在)")


def extract_dialogue_quotes(text: str) -> list[str]:
    """Return spoken-looking quotes from novel excerpt (deduped, order kept)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in _QUOTE_RE.findall(text or ""):
        q = re.sub(r"\s+", "", (raw or "").strip())
        if len(q) < 4 or q in _SKIP_QUOTES or q in seen:
            continue
        if re.fullmatch(r"[…·\.，,。!！?？\s]+", q):
            continue
        seen.add(q)
        out.append(q)
    return out


def _letter_reading(excerpt: str) -> bool:
    return any(k in (excerpt or "") for k in ("信上", "信里", "写道", "留下的信", "绝笔"))


def _is_offscreen_quote(excerpt: str, quote: str) -> bool:
    """True when quote is spoken by crowd / unregistered speaker, not cast."""
    if not quote or quote not in excerpt:
        return False
    idx = excerpt.find(quote)
    before = excerpt[max(0, idx - 32) : idx]
    after = excerpt[idx + len(quote) : idx + len(quote) + 28]
    # 「…」后紧跟群众主语
    if re.match(
        r"^[」』”\"]?\s*(老板娘|随从|渔民|衙役|县令|众人|有人|百姓|旁人|差役|官兵)",
        after,
    ):
        return True
    # 主语在引号前；「盯着随从：」里的随从是宾语，不算说话人
    m = _OFFSCREEN_SPEAKER.search(before)
    if m:
        chunk = before[max(0, m.start() - 4) : m.end()]
        if _ADDRESS_VERB.search(chunk):
            return False
        return True
    return False


def _speaker_for_quote(excerpt: str, quote: str, names: list[str]) -> str | None:
    """Pick the on-screen name that most likely speaks this quote."""
    if not quote or quote not in excerpt or not names:
        return None
    if _is_offscreen_quote(excerpt, quote):
        return None
    idx = excerpt.find(quote)
    before = excerpt[:idx]
    after = excerpt[idx + len(quote) : idx + len(quote) + 36]

    # 「…」林砚之轻声开口
    for name in names:
        if name and name in after and _SPEECH_VERB.search(after):
            return name

    # Score cast names before the quote; skip grammatical objects.
    best_name = None
    best_score = -10**9
    for name in names:
        if not name:
            continue
        pos = before.rfind(name)
        if pos < 0:
            continue
        prev = before[max(0, pos - 2) : pos]
        if prev.endswith("把") or prev.endswith("将"):
            continue
        obj_pat = before[max(0, pos - 4) : pos + len(name)]
        if re.search(rf"(看见|看着|望着|打量){re.escape(name)}", obj_pat):
            continue
        # Nearer to quote is better; clause-leading subject gets a bonus.
        score = pos
        if pos < 12:
            score += 80
        tail = before[pos : pos + 20]
        if _SPEECH_VERB.search(tail):
            score += 120
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def salvage_dialogue(
    lines: list[dict[str, Any]] | None,
    *,
    source_excerpt: str,
    narration: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Fill empty dialogue / narration from quoted speech in source_excerpt.

    - Prefer assigning a quote to the on-screen character named near it.
    - Letter lines with a single on-screen character become that character reading.
    - Quotes from off-screen / unregistered speakers go into narration as 画外口播.
    """
    lines = [dict(ln) for ln in (lines or [])]
    nar = (narration or "").strip()
    excerpt = (source_excerpt or "").strip()
    quotes = extract_dialogue_quotes(excerpt)
    names = [(ln.get("name") or "").strip() for ln in lines]

    # Reclaim only salvage artifacts wrongly glued onto cast (轻声/读信 + offscreen).
    for ln in lines:
        d = (ln.get("dialogue") or "").strip()
        voice = (ln.get("voice_direction") or "").strip()
        if not d or voice not in ("轻声", "读信"):
            continue
        name = (ln.get("name") or "").strip()
        speaker = _speaker_for_quote(excerpt, d, names) if excerpt else None
        if speaker == name:
            continue
        if _letter_reading(excerpt) and len(lines) == 1 and d in quotes:
            continue
        if _is_offscreen_quote(excerpt, d) or (d in quotes and speaker not in (None, name)):
            ln["dialogue"] = ""
            ln["voice_direction"] = ""

    if nar.startswith("画外口播"):
        nar = ""

    if any((ln.get("dialogue") or "").strip() for ln in lines):
        keep = (narration or "").strip()
        if keep.startswith("画外口播"):
            keep = nar
        return lines, keep

    if not quotes:
        return lines, nar if nar else (narration or "").strip()

    assigned: set[str] = set()
    by_name = {(ln.get("name") or "").strip(): ln for ln in lines}

    for q in quotes:
        speaker = _speaker_for_quote(excerpt, q, names)
        if not speaker:
            continue
        ln = by_name.get(speaker)
        if not ln or (ln.get("dialogue") or "").strip():
            continue
        ln["dialogue"] = q
        if not (ln.get("voice_direction") or "").strip():
            if _letter_reading(excerpt):
                ln["voice_direction"] = "读信"
            elif "轻声" in excerpt:
                ln["voice_direction"] = "轻声"
        assigned.add(q)

    # Single cast reading a letter.
    if (
        len(lines) == 1
        and not (lines[0].get("dialogue") or "").strip()
        and quotes
        and _letter_reading(excerpt)
        and not _is_offscreen_quote(excerpt, quotes[0])
    ):
        lines[0]["dialogue"] = quotes[0]
        if not (lines[0].get("voice_direction") or "").strip():
            lines[0]["voice_direction"] = "读信"
        assigned.add(quotes[0])

    leftover = [q for q in quotes if q not in assigned]
    if leftover and (not nar or nar == "无"):
        nar = "画外口播：" + "；".join(f"「{q}」" for q in leftover[:3])
    elif leftover and nar and "画外口播" not in nar:
        nar = f"{nar} 画外口播：" + "；".join(f"「{q}」" for q in leftover[:2])

    return lines, nar
