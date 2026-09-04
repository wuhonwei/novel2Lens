from app.domain.chapters import split_chapters


SAMPLE = """序 雾起
江面有雾。

第一章 雾锁渡口
林砚之站在渡口。

第二章 暗流涌动
赵万山来了。
"""


def test_split_numbered_chinese_chapters():
    parts = split_chapters(SAMPLE)
    titles = [p.title for p in parts]
    assert titles[0] == "序 雾起"
    assert titles[1].startswith("第一章")
    assert titles[2].startswith("第二章")
    assert "林砚之" in parts[1].text
    assert "赵万山" in parts[2].text


def test_split_falls_back_to_chunks_without_headings():
    text = "。".join(["甲" * 40] * 200)
    parts = split_chapters(text, chunk_chars=800)
    assert len(parts) >= 2
    assert all(p.text.strip() for p in parts)
    assert sum(len(p.text) for p in parts) >= len(text) - 20


def test_markdown_headings_count_as_chapters():
    text = "# 开端\nhello\n\n## 转折\nworld"
    parts = split_chapters(text)
    assert len(parts) == 2
    assert parts[0].title == "开端"
    assert "world" in parts[1].text


def test_single_line_book_title_is_not_a_chapter():
    text = "青川渡\n第一章 雾锁渡口\n林砚之站在渡口。\n第二章 暗流\n赵万山来了。"
    parts = split_chapters(text)
    assert parts[0].title.startswith("第一章")
    assert "林砚之" in parts[0].text
    assert len(parts) == 2
