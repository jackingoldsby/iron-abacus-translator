"""Title skip patterns and chapter/skip detection."""

import re

# Patterns indicating non-chapter front/back matter
SKIP_TITLES = {
    "版权信息", "版權信息", "梁羽生先生简介", "梁羽生先生簡介",
    "梁羽生武侠小说作品集", "梁羽生武俠小說作品集",
    "目录", "目錄", "封面", "书名", "書名", "新版电子书序言",
    "新版電子書序言", "前言", "后记", "後記", "附录", "附錄",
}


def is_chapter_title(title: str) -> bool:
    """Check if a title looks like a chapter heading rather than a book title."""
    if not title:
        return False
    title = title.strip()
    return bool(re.match(
        r"^(第[一二三四五六七八九十百零\d]+[回章節节]|楔子|尾聲|尾声|引子|序[章曲]|後記|后记|前言|附錄|附录|"
        r"故事[简簡]介|[梁溫温蕭萧][^　]{1,3}先生[简簡]介|"
        r"[梁溫温蕭萧][^　]{1,3}武[侠俠]小[说說]作品集|版[权權]信息|目[录錄]|封面)",
        title,
    ))


def is_skip_title(title: str) -> bool:
    """Check if title should be skipped (front/back matter)."""
    return title.strip() in SKIP_TITLES
