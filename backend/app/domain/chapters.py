from __future__ import annotations

from dataclasses import dataclass
import re

def _is_book_title(preamble: str) -> bool:
    lines = [ln.strip() for ln in preamble.splitlines() if ln.strip()]
    return len(lines) == 1 and len(lines[0]) <= 40 and "。" not in lines[0]


HEADING = re.compile(
    r"^(?P<title>"
    r"第[0-9一二三四五六七八九十百千零〇两]+章[^\n]*"
    r"|Chapter\s+\d+[^\n]*"
    r"|#{1,3}\s+.+"
    r")\s*$",
    re.MULTILINE | re.IGNORECASE,
)


@dataclass(frozen=True)
class ChapterSlice:
    index: int
    title: str
    text: str


def _clean_md_title(raw: str) -> str:
    return re.sub(r"^#{1,3}\s+", "", raw).strip()


def split_chapters(text: str, chunk_chars: int = 6000) -> list[ChapterSlice]:
    source = (text or "").replace("\r\n", "\n").strip("\n")
    if not source.strip():
        return []

    matches = list(HEADING.finditer(source))
    if matches:
        parts: list[ChapterSlice] = []
        first = matches[0]
        if first.start() > 0:
            preamble = source[: first.start()].strip()
            if preamble and not _is_book_title(preamble):
                first_line = preamble.split("\n", 1)[0].strip() or "序"
                parts.append(ChapterSlice(index=0, title=first_line[:80], text=preamble))
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
            block = source[start:end].strip()
            title = _clean_md_title(match.group("title"))
            parts.append(ChapterSlice(index=len(parts), title=title, text=block))
        return parts

    return _chunk_by_size(source, chunk_chars)


def _chunk_by_size(source: str, chunk_chars: int) -> list[ChapterSlice]:
    paragraphs = re.split(r"\n\s*\n", source)
    if len(paragraphs) <= 1:
        paragraphs = re.split(r"(?<=[。！？；])", source)
        paragraphs = [p for p in paragraphs if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    joiner = "\n\n" if "\n\n" in source else ""
    for para in paragraphs:
        if size and size + len(para) > chunk_chars:
            chunks.append(joiner.join(buf).strip())
            buf = [para]
            size = len(para)
        else:
            buf.append(para)
            size += len(para)
    if buf:
        chunks.append(joiner.join(buf).strip())
    return [
        ChapterSlice(index=i, title=f"第{i + 1}段", text=chunk)
        for i, chunk in enumerate(chunks)
        if chunk
    ]
