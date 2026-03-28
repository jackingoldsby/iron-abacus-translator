#!/usr/bin/env python3
"""
Period Researcher — DeepSeek-powered dynasty art context generation.

Operates at the PERIOD level (not per-book). For a given dynasty, generates
knowledge about art styles, typical subjects, media, and painting schools
that can inform search queries.

Anti-hallucination strategy:
- Dynasty dates are hardcoded in config/dynasty_periods.py — DeepSeek does NOT provide dates
- DeepSeek provides art styles, subjects, media, painting schools — NOT specific
  artwork titles, catalog numbers, or unverifiable artist names
- Artist whitelist in dynasty_periods.py gates which names can be used as primary search terms
- API results (Wikimedia/Met) are the source of truth for actual artworks
"""

import json
import logging
from datetime import datetime
from typing import Optional

from config.dynasty_periods import DYNASTY_PERIODS
from models.portfolio import PeriodResearchResult

logger = logging.getLogger(__name__)

_RESEARCH_PROMPT_BASE = """You are a sinologist and art historian specializing in Chinese visual culture.

Given a Chinese dynasty period, provide FACTUAL knowledge about the art of that era.
This will be used to generate search queries for museum databases (Wikimedia Commons,
Metropolitan Museum Open Access).

Dynasty: {period_label} ({start_year}–{end_year})
{thematic_context}
Provide the following as a JSON object:

{{
  "art_styles": [
    "list of 3-5 painting styles or schools active during this period",
    "e.g. 'Southern School landscape painting', 'literati ink wash'"
  ],
  "typical_subjects": [
    "list of 5-8 common subjects in artwork from this period",
    "e.g. 'mountain landscape with hermit', 'horseback warriors', 'court ladies'"
  ],
  "typical_media": [
    "list of 3-5 art media/formats from this period",
    "e.g. 'hanging scroll ink on silk', 'handscroll ink on paper', 'woodblock print'"
  ]
}}

RULES:
- ONLY factual, well-documented art historical information
- Do NOT invent specific artwork titles or catalog numbers
- Do NOT provide artist names (we have our own verified whitelist)
- Focus on STYLES, SUBJECTS, and MEDIA — these inform search queries
- Be specific to this dynasty, not generic "Chinese art"
- If novel themes are provided, ensure typical_subjects includes subjects that resonate with those themes
"""


class PeriodResearcher:
    """Use DeepSeek to generate period-level art context for search queries."""

    def __init__(self):
        from utils.llm_client import get_deepseek_client
        self.client = get_deepseek_client()

    def research_period(
        self,
        period_slug: str,
        period_label: str,
        thematic_context: Optional[dict] = None,
    ) -> Optional[PeriodResearchResult]:
        """Research art context for a dynasty period.

        Args:
            period_slug: Canonical period slug (e.g. "ming_dynasty")
            period_label: Human label (e.g. "Ming Dynasty")
            thematic_context: Optional dict with top_themes, top_moods,
                century_breakdown, thematic_subjects from theme_extractor

        Returns:
            PeriodResearchResult with art styles, subjects, and media
        """
        dynasty_info = DYNASTY_PERIODS.get(period_slug)
        if not dynasty_info:
            logger.warning(f"Unknown period slug: {period_slug}")
            return None

        _, start_year, end_year = dynasty_info
        start_str = f"{abs(start_year)} BCE" if start_year < 0 else str(start_year)
        end_str = f"{abs(end_year)} BCE" if end_year < 0 else str(end_year)

        # Build thematic context block for the prompt
        theme_block = ""
        if thematic_context:
            parts = []
            if thematic_context.get("top_themes"):
                parts.append(f"Common novel themes set in this period: {', '.join(thematic_context['top_themes'][:8])}")
            if thematic_context.get("top_moods"):
                parts.append(f"Typical mood: {', '.join(thematic_context['top_moods'][:5])}")
            if thematic_context.get("century_breakdown"):
                century_strs = [f"{c}: {n} works" for c, n in thematic_context["century_breakdown"].items()]
                parts.append(f"Century distribution of novels: {'; '.join(century_strs)}")
            if parts:
                theme_block = "\n" + "\n".join(parts) + "\n\nProvide art subjects that resonate with these themes.\n"

        prompt = _RESEARCH_PROMPT_BASE.format(
            period_label=period_label,
            start_year=start_str,
            end_year=end_str,
            thematic_context=theme_block,
        )

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            data = json.loads(content)

            result = PeriodResearchResult(
                period_slug=period_slug,
                period_label=period_label,
                art_styles=data.get("art_styles", []),
                typical_subjects=data.get("typical_subjects", []),
                typical_media=data.get("typical_media", []),
                top_themes=thematic_context.get("top_themes", []) if thematic_context else [],
                top_moods=thematic_context.get("top_moods", []) if thematic_context else [],
                century_breakdown=thematic_context.get("century_breakdown", {}) if thematic_context else {},
                thematic_subjects=thematic_context.get("thematic_subjects", []) if thematic_context else [],
                researched_at=datetime.now(),
            )

            logger.info(
                f"Researched {period_label}: "
                f"{len(result.art_styles)} styles, "
                f"{len(result.typical_subjects)} subjects, "
                f"{len(result.typical_media)} media"
            )
            return result

        except Exception as e:
            logger.error(f"Period research failed for {period_label}: {e}")
            return None
