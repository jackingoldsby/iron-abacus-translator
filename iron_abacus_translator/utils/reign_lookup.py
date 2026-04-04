#!/usr/bin/env python3
"""
Reign Period Lookup Utility

Convert Chinese reign year references (e.g. 康熙十四年) to Western dates
and enrich footnotes with programmatically verified CE dates.

Usage:
    from utils.reign_lookup import ReignLookup

    lookup = ReignLookup()
    lookup.convert("康熙十四年")
    # → "1675 CE (14th year of the Kangxi reign, Qing dynasty)"

    lookup.lookup_reign("康熙")
    # → {"dynasty": "清", "dynasty_en": "Qing Dynasty", ...}

    lookup.enrich_footnote({"ideogram": "康熙十四年", "explanation": "..."})
    # → adds CE date to explanation if missing
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Chinese numeral mappings — reused from chapter_sequence_validator.py
_CHINESE_DIGITS = {
    '零': 0, '〇': 0, '○': 0,
    '一': 1, '壹': 1,
    '二': 2, '貳': 2,
    '三': 3, '參': 3, '叁': 3,
    '四': 4, '肆': 4,
    '五': 5, '伍': 5,
    '六': 6, '陸': 6,
    '七': 7, '柒': 7,
    '八': 8, '捌': 8,
    '九': 9, '玖': 9,
    '十': 10, '拾': 10,
    '廿': 20, '卅': 30, '卌': 40,
}

_POSITION_MULTIPLIERS = {
    '十': 10, '拾': 10,
    '百': 100, '佰': 100,
    '千': 1000, '仟': 1000,
}


def parse_chinese_number(text: str) -> Optional[int]:
    """Parse a Chinese numeral string to an integer.

    Handles: 一 (1), 十一 (11), 二十 (20), 廿一 (21), 一百零一 (101), etc.
    Also handles 元 as 1 (元年 = first year).
    """
    if not text:
        return None

    # 元 = 1 (first year)
    if text == '元':
        return 1

    # Single character
    if len(text) == 1 and text in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[text]

    # 十 at start: 十 = 10, 十一 = 11
    if text[0] in ('十', '拾'):
        if len(text) == 1:
            return 10
        rest = text[1:]
        if rest in _CHINESE_DIGITS:
            return 10 + _CHINESE_DIGITS[rest]

    # 廿/卅/卌 at start
    for prefix, base in [('廿', 20), ('卅', 30), ('卌', 40)]:
        if text.startswith(prefix):
            if len(text) == 1:
                return base
            rest = text[1:]
            if rest in _CHINESE_DIGITS:
                return base + _CHINESE_DIGITS[rest]

    # Compound numbers with position multipliers (二十一, 一百零一, etc.)
    result = 0
    temp = 0

    for char in text:
        if char in _POSITION_MULTIPLIERS:
            mult = _POSITION_MULTIPLIERS[char]
            if temp == 0:
                temp = 1
            result += temp * mult
            temp = 0
        elif char in _CHINESE_DIGITS:
            temp = _CHINESE_DIGITS[char]
        else:
            return None

    result += temp
    return result if result > 0 else None


# Patterns for extracting reign year references from text
# Group 1: reign name (2+ chars), Group 2: year numeral, Group 3: 年
_REIGN_YEAR_PATTERN = re.compile(
    r'([\u4e00-\u9fff]{2,4}?)'          # reign name (2-4 chars, non-greedy)
    r'([元一二三四五六七八九十廿卅卌壹貳參叁肆伍陸柒捌玖拾佰百千零〇○]+)'  # year
    r'年'
)

# Pattern for "reign + 年間" (during the reign of...)
_REIGN_PERIOD_PATTERN = re.compile(
    r'([\u4e00-\u9fff]{2,4}?)年間'
)

# Pattern for "reign + 初年" (early years of...)
_REIGN_EARLY_PATTERN = re.compile(
    r'([\u4e00-\u9fff]{2,4}?)初年'
)

# Pattern for "reign + 末年" (late years of...)
_REIGN_LATE_PATTERN = re.compile(
    r'([\u4e00-\u9fff]{2,4}?)末年'
)


class ReignLookup:
    """Convert Chinese reign year references to Western dates.

    Loads reign period data from DuckDB on first use and caches in memory.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize with optional DB path override."""
        self._db_path = db_path
        self._reign_data: Optional[Dict[str, dict]] = None  # reign_zh -> row
        self._dynasty_data: Optional[Dict[str, List[dict]]] = None  # dynasty_zh -> rows

    def _ensure_loaded(self):
        """Load reign period data from DuckDB if not already cached."""
        if self._reign_data is not None:
            return

        self._reign_data = {}
        self._dynasty_data = {}

        try:
            conn = self._get_connection()
            # Check if table exists
            tables = [r[0] for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = 'reign_periods'"
            ).fetchall()]

            if 'reign_periods' not in tables:
                logger.warning("reign_periods table not found — run seed_reign_periods.py first")
                return

            rows = conn.execute(
                "SELECT dynasty, dynasty_en, reign_name_zh, reign_name_py, reign_name_en, "
                "start_year, end_year, emperor_zh, emperor_py, emperor_en, notes, wiki_url "
                "FROM reign_periods ORDER BY start_year"
            ).fetchall()

            columns = [
                'dynasty', 'dynasty_en', 'reign_name_zh', 'reign_name_py',
                'reign_name_en', 'start_year', 'end_year', 'emperor_zh',
                'emperor_py', 'emperor_en', 'notes', 'wiki_url',
            ]

            for row in rows:
                d = dict(zip(columns, row))
                zh = d['reign_name_zh']
                self._reign_data[zh] = d

                dynasty_zh = d['dynasty']
                if dynasty_zh not in self._dynasty_data:
                    self._dynasty_data[dynasty_zh] = []
                self._dynasty_data[dynasty_zh].append(d)

            logger.info(f"Loaded {len(self._reign_data)} reign periods from DB")
            conn.close()

        except Exception as e:
            logger.error(f"Failed to load reign periods: {e}")
            self._reign_data = {}
            self._dynasty_data = {}

    def _get_connection(self):
        """Get a DuckDB connection to the catalog database."""
        if self._db_path:
            import duckdb
            return duckdb.connect(str(self._db_path))

        from utils.db import connect_catalog
        return connect_catalog()

    def convert(self, text: str) -> Optional[str]:
        """Convert a reign year reference to a formatted Western date string.

        Examples:
            "康熙十四年" → "1675 CE (14th year of the Kangxi reign, Qing dynasty)"
            "雍正三年"   → "1725 CE (3rd year of the Yongzheng reign, Qing dynasty)"
            "建炎元年"   → "1127 CE (1st year of the Jianyan reign, Southern Song dynasty)"
            "乾隆年間"   → "during the Qianlong reign (1736–1795), Qing dynasty"

        Returns None if the text doesn't contain a recognizable reign year reference.
        """
        self._ensure_loaded()

        # Try "年間" (during the reign) pattern
        m = _REIGN_PERIOD_PATTERN.search(text)
        if m:
            reign_zh = m.group(1)
            info = self._reign_data.get(reign_zh)
            if info:
                return (
                    f"during the {info['reign_name_en']} reign "
                    f"({info['start_year']}–{info['end_year']}), "
                    f"{info['dynasty_en']}"
                )

        # Try "初年" (early years) pattern
        m = _REIGN_EARLY_PATTERN.search(text)
        if m:
            reign_zh = m.group(1)
            info = self._reign_data.get(reign_zh)
            if info:
                return (
                    f"early {info['reign_name_en']} reign "
                    f"(c. {info['start_year']}), {info['dynasty_en']}"
                )

        # Try "末年" (late years) pattern
        m = _REIGN_LATE_PATTERN.search(text)
        if m:
            reign_zh = m.group(1)
            info = self._reign_data.get(reign_zh)
            if info:
                return (
                    f"late {info['reign_name_en']} reign "
                    f"(c. {info['end_year']}), {info['dynasty_en']}"
                )

        # Try specific year pattern: 康熙十四年
        m = _REIGN_YEAR_PATTERN.search(text)
        if m:
            reign_zh = m.group(1)
            year_zh = m.group(2)
            info = self._reign_data.get(reign_zh)
            if info:
                year_num = parse_chinese_number(year_zh)
                if year_num is not None:
                    ce_year = info['start_year'] + year_num - 1
                    # Sanity check: year must be within reign
                    if ce_year > info['end_year']:
                        logger.warning(
                            f"Computed year {ce_year} exceeds reign end "
                            f"{info['end_year']} for {reign_zh}{year_zh}年"
                        )
                    ordinal = _ordinal(year_num)
                    return (
                        f"{ce_year} CE ({ordinal} year of the "
                        f"{info['reign_name_en']} reign, {info['dynasty_en']})"
                    )

        return None

    def convert_to_ce(self, text: str) -> Optional[int]:
        """Convert a reign year reference to just the CE year integer.

        Returns None if cannot parse.
        """
        self._ensure_loaded()

        m = _REIGN_YEAR_PATTERN.search(text)
        if m:
            reign_zh = m.group(1)
            year_zh = m.group(2)
            info = self._reign_data.get(reign_zh)
            if info:
                year_num = parse_chinese_number(year_zh)
                if year_num is not None:
                    return info['start_year'] + year_num - 1
        return None

    def lookup_reign(self, reign_zh: str) -> Optional[dict]:
        """Look up a reign period by Chinese name.

        Returns a dict with dynasty, dates, emperor, notes, etc.
        """
        self._ensure_loaded()
        return self._reign_data.get(reign_zh)

    def lookup_dynasty(self, dynasty_zh: str) -> List[dict]:
        """List all reign periods for a dynasty (by Chinese name).

        Returns list of dicts sorted by start_year.
        """
        self._ensure_loaded()
        return self._dynasty_data.get(dynasty_zh, [])

    def enrich_footnote(self, footnote: dict) -> dict:
        """If a footnote mentions a reign year, add the CE date.

        Modifies the footnote dict in place and returns it.
        Only adds if the explanation doesn't already contain a CE date.
        """
        ideogram = footnote.get('ideogram', '')
        explanation = footnote.get('explanation', '')

        # Skip if already has a CE date
        if re.search(r'\d{3,4}\s*CE\b', explanation):
            return footnote

        # Try converting the ideogram itself
        result = self.convert(ideogram)
        if result:
            footnote['explanation'] = f"{result}. {explanation}" if explanation else result
            return footnote

        # Try finding a reign year reference in the explanation
        for pattern in [_REIGN_YEAR_PATTERN, _REIGN_PERIOD_PATTERN]:
            m = pattern.search(explanation)
            if m:
                full_match = m.group(0)
                converted = self.convert(full_match + ('年' if not full_match.endswith('年') else ''))
                if converted:
                    footnote['explanation'] = explanation + f" [{converted}]"
                    return footnote

        return footnote

    def find_reign_references(self, text: str) -> List[Tuple[str, str]]:
        """Find all reign year references in a text block.

        Returns list of (matched_text, conversion) tuples.
        """
        self._ensure_loaded()
        results = []

        for pattern in [_REIGN_YEAR_PATTERN, _REIGN_PERIOD_PATTERN,
                        _REIGN_EARLY_PATTERN, _REIGN_LATE_PATTERN]:
            for m in pattern.finditer(text):
                matched = m.group(0)
                # Ensure it ends with 年 for the year pattern
                query = matched if matched.endswith('年') or matched.endswith('間') else matched + '年'
                converted = self.convert(query)
                if converted:
                    results.append((matched, converted))

        return results

    @property
    def reign_count(self) -> int:
        """Number of loaded reign periods."""
        self._ensure_loaded()
        return len(self._reign_data)

    @property
    def dynasty_names(self) -> List[str]:
        """List of dynasty Chinese names with loaded data."""
        self._ensure_loaded()
        return list(self._dynasty_data.keys())


def _ordinal(n: int) -> str:
    """Return English ordinal string: 1→'1st', 2→'2nd', etc."""
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"
