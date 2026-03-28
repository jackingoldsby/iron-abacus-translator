#!/usr/bin/env python3
"""
Hardcoded dynasty date ranges and known artist whitelists.

DeepSeek does NOT provide dates — this file is the source of truth for
dynasty chronology. DeepSeek may suggest artist names, but only whitelisted
artists are used as primary search terms.
"""

from typing import Dict, List, Tuple

# Canonical dynasty periods with date ranges
# Format: slug -> (label, start_year, end_year)
DYNASTY_PERIODS: Dict[str, Tuple[str, int, int]] = {
    "shang_dynasty": ("Shang Dynasty", -1600, -1046),
    "zhou_dynasty": ("Zhou Dynasty", -1046, -256),
    "warring_states": ("Warring States", -475, -221),
    "qin_dynasty": ("Qin Dynasty", -221, -206),
    "han_dynasty": ("Han Dynasty", -206, 220),
    "three_kingdoms": ("Three Kingdoms", 220, 280),
    "jin_dynasty": ("Jin Dynasty", 266, 420),
    "northern_southern": ("Northern & Southern Dynasties", 420, 589),
    "sui_dynasty": ("Sui Dynasty", 581, 618),
    "tang_dynasty": ("Tang Dynasty", 618, 907),
    "five_dynasties": ("Five Dynasties & Ten Kingdoms", 907, 979),
    "song_dynasty": ("Song Dynasty", 960, 1279),
    "yuan_dynasty": ("Yuan Dynasty", 1271, 1368),
    "ming_dynasty": ("Ming Dynasty", 1368, 1644),
    "qing_dynasty": ("Qing Dynasty", 1644, 1912),
    "republic_era": ("Republic Era", 1912, 1949),
}

# Well-documented artists per dynasty (safe to use as primary search terms)
ARTIST_WHITELIST: Dict[str, List[str]] = {
    "tang_dynasty": [
        "Wu Daozi", "Yan Liben", "Zhang Xuan", "Zhou Fang",
        "Han Gan", "Li Sixun", "Li Zhaodao", "Wang Wei",
    ],
    "five_dynasties": [
        "Dong Yuan", "Juran", "Gu Hongzhong", "Li Cheng",
        "Xu Xi", "Huang Quan",
    ],
    "song_dynasty": [
        "Fan Kuan", "Guo Xi", "Ma Yuan", "Xia Gui",
        "Li Tang", "Zhang Zeduan", "Emperor Huizong",
        "Liu Songnian", "Su Shi", "Mi Fu", "Liang Kai",
        "Mu Qi", "Li Gonglin", "Zhao Ji",
    ],
    "yuan_dynasty": [
        "Zhao Mengfu", "Huang Gongwang", "Wu Zhen",
        "Ni Zan", "Wang Meng", "Guan Daosheng",
    ],
    "ming_dynasty": [
        "Shen Zhou", "Wen Zhengming", "Tang Yin", "Qiu Ying",
        "Dong Qichang", "Xu Wei", "Chen Hongshou",
        "Dai Jin", "Wu Wei", "Lu Zhi",
    ],
    "qing_dynasty": [
        "Wang Hui", "Wang Shimin", "Wang Jian", "Wang Yuanqi",
        "Bada Shanren", "Shitao", "Kun Can", "Hong Ren",
        "Yun Shouping", "Giuseppe Castiglione", "Ren Bonian",
        "Wu Changshuo", "Qi Baishi",
    ],
}


def normalize_period(raw_period: str) -> Tuple[str, str]:
    """Normalize a free-text period string to a canonical (slug, label) pair.

    Handles the various forms found in the DuckDB catalog:
    - "Ming Dynasty"
    - "Ming Dynasty (implied)"
    - "Late Ming Dynasty"
    - "Song-Yuan dynasties (12th-14th century)"
    - "Tang dynasty (8th century, An Lushan Rebellion)"
    - "Jianghu world" / unspecified → "unspecified"

    Returns:
        (slug, label) tuple. Falls back to ("unspecified", "Unspecified Period").
    """
    if not raw_period:
        return ("unspecified", "Unspecified Period")

    text = raw_period.lower().strip()

    # Direct dynasty keyword matching (order from specific to general)
    dynasty_keywords = [
        ("three kingdoms", "three_kingdoms"),
        ("warring states", "warring_states"),
        ("northern and southern", "northern_southern"),
        ("northern & southern", "northern_southern"),
        ("five dynasties", "five_dynasties"),
        ("republic", "republic_era"),
        ("tang", "tang_dynasty"),
        ("song", "song_dynasty"),
        ("yuan", "yuan_dynasty"),
        ("ming", "ming_dynasty"),
        ("qing", "qing_dynasty"),
        ("han", "han_dynasty"),
        ("jin", "jin_dynasty"),
        ("sui", "sui_dynasty"),
        ("qin", "qin_dynasty"),
        ("zhou", "zhou_dynasty"),
        ("shang", "shang_dynasty"),
    ]

    for keyword, slug in dynasty_keywords:
        if keyword in text:
            label = DYNASTY_PERIODS[slug][0]
            return (slug, label)

    # Catch-all for jianghu/unspecified/fantasy
    unspecified_signals = [
        "jianghu", "unspecified", "unclear", "fantasy",
        "fictional", "mythical", "not specific", "generic",
        "ancient china",
    ]
    if any(signal in text for signal in unspecified_signals):
        return ("unspecified", "Unspecified Period")

    return ("unspecified", "Unspecified Period")


def get_whitelisted_artists(period_slug: str) -> List[str]:
    """Return whitelisted artists for a period, or empty list."""
    return ARTIST_WHITELIST.get(period_slug, [])
