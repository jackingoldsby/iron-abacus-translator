#!/usr/bin/env python3
"""
Cover Image Researcher — DeepSeek-powered art search term generation.

Analyzes book metadata (title, author, period, setting) to suggest
search queries for public domain artwork suitable as a cover image.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CoverSearchSuggestion:
    """A suggested search query for cover artwork."""
    query: str
    expected_source: str
    period_keywords: List[str]
    rationale: str


_RESEARCH_PROMPT = """You are an art historian specializing in Chinese visual culture across dynasties.

Given this wuxia novel's metadata, suggest 3 search queries for GENUINE HISTORICAL
artwork from the actual period depicted in the novel. These will be used as EPUB covers.

CRITICAL REQUIREMENTS — read carefully:
- ONLY authentic period artwork: paintings, scrolls, woodblock prints, album leaves,
  murals, or calligraphy actually produced during or near the depicted era
- NO modern illustrations, NO digital art, NO AI-generated images, NO reproductions
- NO "Chinese style" art by non-Chinese or modern artists
- Prefer: Song/Yuan/Ming/Qing dynasty paintings, Tang dynasty murals, period woodblock prints
- Identify the specific dynasty or era the novel is set in and target art from that period
- Include the artist's name when a specific work is known (e.g. "Ma Yuan mountain landscape")
- For martial/swordsman themes: period depictions of warriors, swords, horses — not modern manga

Search sources are Wikimedia Commons and the Metropolitan Museum Open Access collection.
Craft queries that will find actual museum-held or digitized historical pieces.

Return a JSON object with key "suggestions" containing an array of objects:
{{
  "suggestions": [
    {{
      "query": "specific search query targeting a real historical artwork or artist",
      "expected_source": "wikimedia_commons" or "met_museum",
      "period_keywords": ["dynasty name", "art style/school", "medium", "approximate date range"],
      "rationale": "why this period artwork suits this novel's setting and themes"
    }}
  ]
}}

Novel metadata:
- Title (Chinese): {title_zh}
- Title (English): {title_en}
- Author: {author_en} ({author_zh})
- Work number: {work_number}
"""


class CoverResearcher:
    """Use DeepSeek to analyze book metadata and suggest cover art search terms."""

    def __init__(self):
        from utils.llm_client import get_deepseek_client
        self.client = get_deepseek_client()

    def suggest_searches(
        self,
        meta: Dict[str, Any],
        title_en: str = "",
        author_en: str = "",
    ) -> List[CoverSearchSuggestion]:
        """Analyze book metadata and return cover art search suggestions.

        Args:
            meta: Book metadata dict (from translated JSON)
            title_en: English title (optional, extracted from meta if not provided)
            author_en: English author (optional, extracted from meta if not provided)

        Returns:
            List of CoverSearchSuggestion with search queries
        """
        title_zh = meta.get("title", "")
        author_zh = meta.get("author", "")
        work_number = meta.get("work_number", "unknown")

        if not title_en:
            title_en = meta.get("translation", {}).get("title", title_zh)
        if not author_en:
            author_en = meta.get("translation", {}).get("author", author_zh)

        prompt = _RESEARCH_PROMPT.format(
            title_zh=title_zh,
            title_en=title_en,
            author_en=author_en,
            author_zh=author_zh,
            work_number=work_number,
        )

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            data = json.loads(content)

            # Handle both {"suggestions": [...]} and direct array
            suggestions_raw = data if isinstance(data, list) else data.get("suggestions", [])

            suggestions = []
            for s in suggestions_raw[:3]:
                suggestions.append(CoverSearchSuggestion(
                    query=s.get("query", ""),
                    expected_source=s.get("expected_source", "wikimedia_commons"),
                    period_keywords=s.get("period_keywords", []),
                    rationale=s.get("rationale", ""),
                ))

            logger.info(f"Generated {len(suggestions)} cover search suggestions for {work_number}")
            return suggestions

        except Exception as e:
            logger.error(f"Cover research failed: {e}")
            # Return a generic fallback
            return [CoverSearchSuggestion(
                query=f"Chinese painting {title_en} martial arts",
                expected_source="wikimedia_commons",
                period_keywords=["Chinese", "painting", "martial arts"],
                rationale="Generic fallback query",
            )]
