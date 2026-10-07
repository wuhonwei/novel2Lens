"""Salvage spoken lines from storyboard source excerpts into H3 dialogue."""
from __future__ import annotations

import re
from typing import Any

# Chinese / ASCII quote pairs commonly used in novels.
_QUOTE_RE = re.compile(r"[「『“\"]([^」』”\"]{2,160})[」』”\"]")

# Short seals / names that look like quotes but are not spoken lines.
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


def extract_dialogue_quotes(text: str) -> list[str]:
    """Return spoken-looking quotes from novel excerpt (deduped, order kept)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in _QUOTE_RE.findall(text or ""):
        q = re.sub(r"\s+", "", (raw or "").strip())
        if len(q) < 4 or q in _SKIP_QUOTES or q in seen:
            continue
        # Skip pure punctuation / ellipsis shards.
        if re.fullmatch(r"[…·\.，,。!！?？\s]+", q):
            continue
        seen.add(q)
        out.append(q)
    return out


def _name_near_quote(excerpt: str, quote: str, name: str) -> bool:
    if not name or not quote or quote not in excerpt:
        return False
    idx = excerpt.find(quote)
    # Prefer text around the opening quote mark.
    window_start = max(0, idx - 36)
    window_end = min(len(excerpt), idx + len(quote) + 36)
    window = excerpt[window_start:window_end]
    if name not in window:
        return False
    # Require a speech cue near the name or quote, or letter-reading cue.
    if _SPEECH_VERB.search(window):
        return True
    if any(k in excerpt for k in ("信上", "写道", "念道", "念了一句", "读")):
        return True
    return False


def _letter_reading(excerpt: str) -> bool:
    return any(k in (excerpt or "") for k in ("信上", "信里", "写道", "留下的信", "绝笔"))


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
    Existing non-empty dialogue / narration are left alone.
    """
    lines = [dict(ln) for ln in (lines or [])]
    nar = (narration or "").strip()
    if any((ln.get("dialogue") or "").strip() for ln in lines):
        return lines, nar
    if nar and nar not in ("无",):
        # Keep author narration; still try to attach character dialogue if possible.
        pass

    excerpt = (source_excerpt or "").strip()
    quotes = extract_dialogue_quotes(excerpt)
    if not quotes:
        return lines, nar

    assigned: set[str] = set()
    # 1) Attribute quotes to named on-screen speakers.
    for ln in lines:
        name = (ln.get("name") or "").strip()
        if not name or (ln.get("dialogue") or "").strip():
            continue
        for q in quotes:
            if q in assigned:
                continue
            if _name_near_quote(excerpt, q, name):
                ln["dialogue"] = q
                if not (ln.get("voice_direction") or "").strip():
                    if _letter_reading(excerpt):
                        ln["voice_direction"] = "读信"
                    elif "轻声" in excerpt:
                        ln["voice_direction"] = "轻声"
                assigned.add(q)
                break

    # 2) Single cast + letter / sole quote → character reads aloud.
    if (
        len(lines) == 1
        and not (lines[0].get("dialogue") or "").strip()
        and quotes
        and (_letter_reading(excerpt) or len(quotes) == 1)
    ):
        # Only auto-assign if the quote is not clearly another speaker's line.
        other_speaker = False
        for q in quotes:
            # 「…」后紧跟非本角色名说话 — skip auto assign for crowd lines.
            if re.search(rf"[」』”\"]\s*(?!{re.escape(lines[0].get('name') or '')})\S{{1,8}}(说|道|问|喊)", excerpt):
                other_speaker = True
                break
            before = excerpt.split(q, 1)[0][-24:]
            if re.search(r"(老板娘|随从|渔民|衙役|县令|众人|有人)", before):
                other_speaker = True
                break
        if not other_speaker:
            q = quotes[0]
            lines[0]["dialogue"] = q
            if not (lines[0].get("voice_direction") or "").strip():
                lines[0]["voice_direction"] = "读信" if _letter_reading(excerpt) else "轻声"
            assigned.add(q)

    # 3) Leftover spoken quotes → narration VO (off-screen / crowd / official).
    leftover = [q for q in quotes if q not in assigned]
    if leftover and (not nar or nar == "无"):
        joined = "；".join(f"「{q}」" for q in leftover[:3])
        nar = f"画外口播：{joined}"
    elif leftover and nar and "画外口播" not in nar:
        joined = "；".join(f"「{q}」" for q in leftover[:2])
        nar = f"{nar} 画外口播：{joined}"

    return lines, nar
