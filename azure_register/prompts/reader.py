#!/usr/bin/env python3
"""
Reader enrichment prompt — wuxia literary critic persona.

Produces subjective/evaluative metadata: rating_tier, themes, mood, etc.
"""

VALID_RATING_TIERS = {"masterpiece", "acclaimed", "solid", "minor", "obscure", "controversial"}


def validate_rating_tier(tier: str | None) -> str | None:
    """Validate and normalize rating_tier to one of the 6 fixed values."""
    if not tier:
        return None
    normalized = tier.strip().lower()
    if normalized in VALID_RATING_TIERS:
        return normalized
    # Fuzzy matching for common variations
    for valid in VALID_RATING_TIERS:
        if valid in normalized or normalized in valid:
            return valid
    return None


def format_batch(works: list[dict], authors_db: dict[str, dict]) -> str:
    """Build a user message for DeepSeek to provide reader-oriented assessments.

    Args:
        works: List of work dicts from DB query.
        authors_db: All authors keyed by name_chinese.

    Returns:
        Prompt string.
    """
    works_text = []
    for i, w in enumerate(works, 1):
        parts = [f"{i}. work_number={w['work_number']}"]
        if w.get("title_chinese"):
            parts.append(f"title_zh={w['title_chinese']}")
        if w.get("title_english"):
            parts.append(f"title_en={w['title_english']}")
        if w.get("author_chinese"):
            parts.append(f"author_zh={w['author_chinese']}")
        if w.get("author_english"):
            parts.append(f"author_en={w['author_english']}")
        if w.get("publication_year"):
            parts.append(f"pub_year={w['publication_year']}")
        if w.get("summary"):
            parts.append(f"summary={w['summary']}")
        if w.get("category_english"):
            parts.append(f"genre={w['category_english']}")
        if w.get("setting_period"):
            parts.append(f"setting={w['setting_period']}")
        works_text.append(", ".join(parts))

    works_block = "\n".join(works_text)

    # Collect unique authors in this batch
    authors_in_batch = {}
    for w in works:
        az = w.get("author_chinese")
        if az and az not in authors_in_batch:
            authors_in_batch[az] = w.get("author_english", "")

    author_lines = [f"  - {az} ({ae})" for az, ae in authors_in_batch.items()]
    authors_block = "\n".join(author_lines)

    return f"""As a fellow wuxia literary critic and Chinese fiction scholar, I need your expertise to provide reader-oriented assessments of these works. Your deep knowledge of the wuxia canon, author reputations, and genre evolution is essential.

For each work, provide subjective but informed literary assessments that help a reader decide what to read next. Rate works relative to the wuxia/martial arts fiction genre, not all literature.

WORKS:
{works_block}

AUTHORS IN THIS BATCH:
{authors_block}

Return a JSON object with two keys:

1. "works": an array of objects, one per work, each with:
   - "work_number": (echo back)
   - "rating_tier": EXACTLY one of: "masterpiece", "acclaimed", "solid", "minor", "obscure", "controversial"
     * masterpiece: universally recognized pinnacle of the genre (reserve for ~5-10 works total across all wuxia)
     * acclaimed: widely praised, considered among an author's best or a genre landmark
     * solid: well-crafted, enjoyable, but not the author's peak work
     * minor: lesser work, perhaps early/experimental or formulaic
     * obscure: little-known, limited critical attention
     * controversial: divisive \u2014 some love it, some hate it, or significant critical debate
   - "rating_note": 1-2 sentences of critical context. WHY this tier? What do critics/readers say?
   - "writing_style": comma-separated style descriptors (use 2-5):
     poetic, lyrical, spare, dense, cinematic, theatrical, cerebral, visceral,
     character-driven, plot-driven, slow-burn, fast-paced, episodic, tightly-plotted,
     literary, pulpy, philosophical, humorous, satirical, tragic, romantic,
     classical-prose, vernacular, experimental
   - "themes": comma-separated thematic tags (use 2-5):
     forbidden love, revenge cycle, political intrigue, identity, loyalty vs righteousness,
     jianghu honor code, master-disciple bond, power corruption, redemption, sacrifice,
     family legacy, ethnic conflict, dynastic collapse, wandering hero, reclusion,
     coming-of-age, gender subversion, class struggle, fate vs free will, brotherhood
     (or other relevant themes)
   - "mood": comma-separated tone/atmosphere tags (use 2-4):
     dark, melancholy, romantic, suspenseful, epic, intimate, nostalgic, brooding,
     whimsical, bleak, triumphant, bittersweet, tense, lighthearted, ominous,
     grand, meditative, frenetic
   - "comparable_works": 1 sentence \u2014 "If you liked X, you'll enjoy this" or "Fans of X will appreciate Y".
   - "wuxia_era": era label + brief context. Format: "era_label (context)"
     * "foundational (1950s new-school pioneer)"
     * "golden age (1960s-70s peak of Jin Yong/Gu Long rivalry)"
     * "late classical (1980s mature genre)"
     * "post-classical (1990s+ genre reinvention)"
     * "pre-modern (Republican era or earlier)"

2. "authors": an array of objects, one per unique author, each with:
   - "name_chinese": (echo back)
   - "writing_style": author's signature literary style in 1-2 sentences
   - "best_known_for": signature works and contributions in 1-2 sentences

Return ONLY the JSON object. No markdown fences, no commentary.
If you're uncertain about a specific work, use your best scholarly judgment \u2014 an informed assessment is better than null."""
