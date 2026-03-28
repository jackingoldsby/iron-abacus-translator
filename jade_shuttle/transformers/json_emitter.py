"""JSON generation — THE CONTRACT BOUNDARY.

The output of generate_json() must match what iron_abacus_translator expects.
Never change this format without coordinating with the translation pipeline.

Contract:
{
  "metadata": {"title": str, "creator": str, "language": "zh-Hant", "source": str, "publisher": str|null},
  "source": str,
  "number_of_characters": int,
  "toc": [{"full_title": str, "chapter_ref": str}],
  "chapters": [{"title": str, "content": [{"tag": str, "content": str}]}]
}
"""

from typing import Dict

from models.core import DetectedWork


def generate_json(work: DetectedWork, work_number: str) -> Dict:
    """Generate pipeline-compatible raw JSON for a single work/volume."""
    chapters_json = []
    for ch in work.chapters:
        chapters_json.append({
            "title": ch.title,
            "content": ch.content,
        })

    toc_entries = []
    for i, ch in enumerate(chapters_json):
        toc_entries.append({
            "full_title": ch["title"],
            "chapter_ref": f"chapter_{i}",
        })

    return {
        "metadata": {
            "title": work.title_traditional,
            "creator": work.author_traditional,
            "language": "zh-Hant",
            "source": "Anna's Archive",
            "publisher": None,
        },
        "source": f"{work_number}.epub",
        "number_of_characters": work.character_count,
        "toc": toc_entries,
        "chapters": chapters_json,
    }
