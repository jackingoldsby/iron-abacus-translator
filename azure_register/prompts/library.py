#!/usr/bin/env python3
"""
Library enrichment prompt — sinologist/wuxia scholar persona.

Produces factual metadata: publication_year, setting_period, summary, etc.
"""


def format_batch(works: list[dict], authors_db: dict[str, dict]) -> str:
    """Build a user message for DeepSeek to enrich a batch of works.

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
            parts.append(f"title_en_current={w['title_english']}")
        if w.get("author_chinese"):
            parts.append(f"author_zh={w['author_chinese']}")
        if w.get("author_english"):
            parts.append(f"author_en_current={w['author_english']}")
        if w.get("work_link"):
            parts.append(f"link={w['work_link']}")
        works_text.append(", ".join(parts))

    works_block = "\n".join(works_text)

    # Collect unique authors in this batch
    authors_in_batch = {}
    for w in works:
        az = w.get("author_chinese")
        if az and az not in authors_in_batch:
            authors_in_batch[az] = w.get("author_english", "")

    author_lines = [f"  - {az} (current English: {ae})" for az, ae in authors_in_batch.items()]
    authors_block = "\n".join(author_lines)

    return f"""As a fellow sinologist and wuxia scholar, I need your expertise to validate and enrich metadata for these Chinese literary works. Your knowledge of Chinese publishing history, author biographies, and literary conventions is essential here.

For each work below, please provide validated/corrected metadata. Be precise \u2014 use your knowledge of actual publication dates (first serialization, not later reprints), author biographical facts, and accurate literary English translations of titles.

WORKS:
{works_block}

AUTHORS IN THIS BATCH:
{authors_block}

Return a JSON object with two keys:

1. "works": an array of objects, one per work, each with:
   - "work_number": (echo back)
   - "title_english": canonical English title (proper literary translation, not pinyin. Use established translations where they exist, e.g. \u5c04\u9d70\u82f1\u96c4\u50b3 = "Legend of the Condor Heroes")
   - "publication_year": year of first serialization (integer, or null if truly unknown)
   - "publication_note": brief publication context (e.g. "Serialized in Ming Pao, 1959\u20131961"), or null
   - "setting_period": historical setting if applicable (e.g. "Song Dynasty, 1199\u20131227"), or null for contemporary/unclear
   - "summary": 1-2 sentence synopsis without spoilers. Focus on setting, protagonist, and central conflict.
   - "category_english": genre tags as comma-separated string (from: wuxia, martial_arts, romance, historical, mystery, adventure, comedy, tragedy, revenge, political, supernatural, jianghu, science_fiction, detective, thriller, fantasy)

2. "authors": an array of objects, one per unique author, each with:
   - "name_chinese": (echo back)
   - "birth_year": integer or null
   - "death_year": integer or null (use null if still living)
   - "pen_name_origin": brief etymology of pen name if known (e.g. "From combining characters of his real name Zh\u0101 Li\u00e1ngy\u014dng \u67e5\u826f\u938d"), or null
   - "wikipedia_url": English Wikipedia URL if one exists, or null

Return ONLY the JSON object. No markdown fences, no commentary.
If you're uncertain about a field, use your best scholarly judgment rather than leaving it null."""
