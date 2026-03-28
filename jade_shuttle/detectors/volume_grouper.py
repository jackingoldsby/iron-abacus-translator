"""Volume grouping — group multi-volume works together."""

import re
from typing import Dict, List, Tuple

from models.core import DetectedWork, WorkGroup
from transformers.encoding import S2T


def strip_volume_marker(title: str) -> Tuple[str, str]:
    """Strip volume markers from title, return (base_title, volume_marker).

    Examples:
        "七剑下天山（上册）" -> ("七剑下天山", "上册")
        "江湖三女侠（中册）" -> ("江湖三女侠", "中册")
        "风尘侠隐鹰爪王10" -> ("风尘侠隐鹰爪王", "10")
        "荒江女侠十七" -> ("荒江女侠", "十七")
        "白发魔女传" -> ("白发魔女传", "")
    """
    patterns = [
        # Parenthesized: （上册）, (第三册)
        (r"[（(]([上中下])[册冊]?[)）]$", r"[（(][上中下][册冊]?[)）]$"),
        (r"[（(]第([一二三四五六七八九十\d]+)[册冊卷][)）]$", r"[（(]第[一二三四五六七八九十\d]+[册冊卷][)）]$"),
        # Suffix: ·上册, 上册
        (r"·?([上中下])[册冊]?$", r"·?[上中下][册冊]?$"),
        (r"·?第([一二三四五六七八九十\d]+)[册冊卷]$", r"·?第[一二三四五六七八九十\d]+[册冊卷]$"),
        # "·第N册 Subtitle" pattern: 凌渡宇合集·第一册 月魔
        (r"·第[一二三四五六七八九十\d]+[册冊]\s*.+$", r"·第[一二三四五六七八九十\d]+[册冊]\s*.+$"),
        # "·第N卷 Subtitle" pattern: 大剑师传奇·第一卷 魔女国
        (r"·第[一二三四五六七八九十\d]+[卷]\s*.+$", r"·第[一二三四五六七八九十\d]+[卷]\s*.+$"),
        # "·卷N" pattern: 天地明环·卷二
        (r"·卷[一二三四五六七八九十\d]+$", r"·卷[一二三四五六七八九十\d]+$"),
        # Chinese numeral suffix: 荒江女侠十七, 鹰爪王一
        (r"([一二三四五六七八九十百]+)$", r"[一二三四五六七八九十百]+$"),
        # Arabic numeral suffix: 鹰爪王10, 鹰爪王1
        (r"(\d+)$", r"\d+$"),
    ]

    for capture_re, strip_re in patterns:
        m = re.search(capture_re, title)
        if m:
            base = re.sub(strip_re, "", title).strip()
            marker = m.group(0)
            if len(base) >= 2:
                return base, marker

    return title, ""


def group_volumes(works: List[DetectedWork]) -> List[WorkGroup]:
    """Group detected works into logical works with volumes."""
    groups: Dict[str, List[DetectedWork]] = {}
    order: List[str] = []

    for work in works:
        base, marker = strip_volume_marker(work.title_simplified)
        work.volume_label = marker
        work.volume_group = base

        if base not in groups:
            groups[base] = []
            order.append(base)
        groups[base].append(work)

    result = []
    for base_title in order:
        vols = groups[base_title]
        author_simp = vols[0].author_simplified
        author_trad = vols[0].author_traditional
        base_trad = S2T.convert(base_title)

        group = WorkGroup(
            base_title_trad=base_trad,
            base_title_simp=base_title,
            author_trad=author_trad,
            author_simp=author_simp,
            volumes=vols,
        )
        result.append(group)

    return result
