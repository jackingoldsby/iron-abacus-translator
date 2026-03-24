#!/usr/bin/env python3
"""
Glossary-Aware Context Builder

A replacement for translator.py's _build_glossary_context() that respects
the glossary's deduplication_strategy field and uses the FootnoteContextAccumulator
to suppress already-footnoted terms.

The existing translator.py method remains unchanged. This module is used
by new translation runs that opt into dedup-aware context building.

Usage:
    from utils.glossary_context_builder import build_glossary_context
    from utils.footnote_context import FootnoteContextAccumulator

    accumulator = FootnoteContextAccumulator()
    context = build_glossary_context(matches, accumulator)
"""

import logging
from typing import List, Optional, Tuple

from utils.glossary import GlossaryEntry
from utils.footnote_context import FootnoteContextAccumulator

logger = logging.getLogger(__name__)


def build_glossary_context(
    matches: List[Tuple[str, GlossaryEntry, int]],
    accumulator: Optional[FootnoteContextAccumulator] = None,
) -> str:
    """
    Build glossary context that respects deduplication strategies.

    Unlike the original _build_glossary_context(), this version:
    - Suppresses footnotes for FIRST_OCCURRENCE_ONLY terms already seen
    - Outputs brief-only instructions for RECURRING_BRIEF terms already seen
    - Passes through EVERY_OCCURRENCE terms unchanged
    - Removes the blanket "Add footnotes for ALL occurrences" instruction

    Args:
        matches: List of (term, GlossaryEntry, position) tuples from glossary scan
        accumulator: Optional accumulator tracking previously footnoted terms.
                     If None, behaves like the original (full footnotes for all).

    Returns:
        Formatted glossary context string to append to translation prompt
    """
    if not matches:
        return ""

    full_footnote_terms = []
    brief_footnote_terms = []
    suppressed_terms = []

    for term, entry, pos in matches:
        already_seen = (
            accumulator is not None
            and accumulator.is_already_footnoted(entry.chinese)
        )

        if not already_seen:
            # First occurrence -- full footnote
            full_footnote_terms.append((term, entry))
        elif entry.deduplication_strategy == "EVERY_OCCURRENCE":
            # Always footnote regardless
            full_footnote_terms.append((term, entry))
        elif entry.deduplication_strategy == "RECURRING_BRIEF":
            # Brief mention only
            brief_footnote_terms.append((term, entry))
        else:
            # FIRST_OCCURRENCE_ONLY and already seen -- suppress
            suppressed_terms.append((term, entry))

    context_parts = [
        "\n\n**GLOSSARY TERMS FOUND IN THIS TEXT:**\n"
    ]

    # Full footnote terms
    if full_footnote_terms:
        context_parts.append(
            "\nThe following terms appear for the first time (or require full footnotes). "
            "Use EXACTLY these forms and footnotes:\n"
        )
        for i, (term, entry) in enumerate(full_footnote_terms, 1):
            context_parts.append(f"\n{i}. **{term}** ({entry.chinese})")
            context_parts.append(f"   - Pinyin: {entry.pinyin}")
            context_parts.append(f"   - Translation Strategy: {entry.translation_strategy}")
            context_parts.append(f"   - Recommended Form: {entry.recommended_form}")
            context_parts.append(f"   - Footnote Template: {entry.footnote_template}")

    # Brief footnote terms
    if brief_footnote_terms:
        context_parts.append(
            "\n\nThe following terms have already been explained earlier. "
            "Use a BRIEF footnote only (pinyin + 3-5 word reminder):\n"
        )
        for term, entry in brief_footnote_terms:
            context_parts.append(
                f"- **{term}** ({entry.chinese}): "
                f"Brief footnote only: {entry.chinese} *{entry.pinyin}*"
            )

    # Suppressed terms
    if suppressed_terms:
        context_parts.append(
            "\n\nThe following terms have already been explained earlier in the work. "
            "Do NOT create footnotes for them -- just use the recommended form inline:\n"
        )
        for term, entry in suppressed_terms:
            context_parts.append(
                f"- **{term}** ({entry.chinese}): "
                f"Use '{entry.recommended_form}' inline, NO footnote"
            )

    context_parts.append("\n\n**INSTRUCTIONS:**")
    context_parts.append("- Use the EXACT 'Recommended Form' when translating each term")
    context_parts.append("- Use the EXACT 'Pinyin' (with tone marks) for consistency")
    context_parts.append("- Only create footnotes as specified above (full, brief, or none)")
    context_parts.append(
        "- Ensure glossary footnotes and custom footnotes use the same JSON structure\n"
    )

    return "\n".join(context_parts)
