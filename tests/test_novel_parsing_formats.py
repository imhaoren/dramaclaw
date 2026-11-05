"""不同文本格式/篇幅/章节结构下的解析能力测试。"""

from __future__ import annotations

import pytest

from novelvideo.api.chapter_preview import build_chapter_preview


def _body(index: int, repeat: int = 3) -> str:
    return f"这是第{index}章的正文内容，主角继续推进剧情。" * repeat


def test_parses_chinese_numeral_chapter_headings():
    novel = f"第一章 入宫\n{_body(1)}\n第二章 交锋\n{_body(2)}\n第三章 反击\n{_body(3)}"
    preview = build_chapter_preview(novel)

    assert preview["count"] == 3
    assert [chapter["number"] for chapter in preview["chapters"]] == [1, 2, 3]
    assert preview["chapters"][0]["title"].startswith("第一章")


def test_parses_arabic_chapter_headings():
    novel = "\n".join(f"第{i}章 章节标题{i}\n{_body(i)}" for i in range(1, 6))
    preview = build_chapter_preview(novel)

    assert preview["count"] == 5
    assert preview["chapters"][-1]["number"] == 5


def test_parses_markdown_style_headings():
    novel = "\n".join(
        f"# 第{i}章 标题{i}\n\n{_body(i)}" for i in range(1, 4)
    )
    preview = build_chapter_preview(novel)

    assert preview["count"] == 3
    # 章节正文保留标题行本身，正文紧接其后；只校验内容被完整切到该章。
    assert "这是第2章" in preview["chapters"][1]["content"]


def test_parses_english_chapter_headings():
    novel = "\n".join(
        f"Chapter {i}\n\n{_body(i)}" for i in range(1, 4)
    )
    preview = build_chapter_preview(novel)

    assert preview["count"] == 3


def test_long_novel_with_many_chapters_is_parsed_without_truncation():
    chapters = 120
    novel = "\n".join(
        f"第{i}章 标题{i}\n{_body(i, repeat=20)}" for i in range(1, chapters + 1)
    )
    preview = build_chapter_preview(novel)

    assert preview["count"] == chapters
    assert preview["chapters"][0]["number"] == 1
    assert preview["chapters"][-1]["number"] == chapters


def test_text_without_chapter_headings_falls_back_to_a_single_chapter():
    preview = build_chapter_preview("这是一段没有章节标题的短文本。")

    assert preview["count"] >= 1
    assert preview["chapters"][0]["word_count"] > 0


@pytest.mark.parametrize("separator", ["\r\n", "\n", "\r"])
def test_newline_variants_are_normalized(separator):
    novel = separator.join(
        ["第1章 开端", _body(1), "第2章 发展", _body(2)]
    )
    preview = build_chapter_preview(novel)

    assert preview["count"] == 2
