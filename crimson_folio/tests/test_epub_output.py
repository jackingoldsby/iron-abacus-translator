#!/usr/bin/env python3
"""
Tests for Crimson Folio EPUB output.

Validates EPUB generation from translated JSON, including
content rendering, footnotes, and metadata.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# Minimal translated JSON for testing
SAMPLE_DATA = {
    "meta": {
        "work_number": "TEST01",
        "title": "測試書",
        "author": "測試作者",
        "translation": {
            "title": "Test Book",
            "author": "Test Author",
        },
    },
    "structure": {
        "body": {
            "chapters": [
                {
                    "id": "chapter_001",
                    "title": "第一回 測試章節",
                    "title_english": "Chapter 1: Test Chapter",
                    "title_chinese": "第一回 測試章節",
                    "content_blocks": [
                        {
                            "id": "block_0001",
                            "type": "paragraph",
                            "content": "這是測試內容。",
                            "translated_content": "This is test content with a footnote[1] about martial arts.",
                            "content_type": "narrative",
                            "footnotes": [
                                {
                                    "key": 1,
                                    "ideogram": "武術",
                                    "pinyin": "wǔshù",
                                    "explanation": "Martial arts — the collective term for Chinese fighting systems.",
                                }
                            ],
                        },
                        {
                            "id": "block_0002",
                            "type": "paragraph",
                            "content": "「你好！」他說。",
                            "translated_content": '"Hello!" he said.',
                            "content_type": "dialogue",
                            "footnotes": [],
                        },
                    ],
                },
            ],
        },
    },
}


@pytest.fixture
def sample_json(tmp_path):
    """Write sample translated JSON to a temp file."""
    json_path = tmp_path / "translated_TEST01.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(SAMPLE_DATA, f, ensure_ascii=False)
    return json_path


class TestEpubBuilder:
    """Test EPUB generation."""

    def test_build_creates_epub(self, sample_json, tmp_path):
        """Test that build() creates a valid .epub file."""
        from builders.epub_builder import EpubBuilder

        output = tmp_path / "test.epub"
        builder = EpubBuilder(catalog_db=Path("/nonexistent"))  # skip catalog
        result = builder.build(sample_json, output)

        assert result.exists()
        assert result.suffix == ".epub"
        assert result.stat().st_size > 0

    def test_build_from_data(self, tmp_path):
        """Test build_from_data with in-memory dict."""
        from builders.epub_builder import EpubBuilder

        output = tmp_path / "test.epub"
        builder = EpubBuilder(catalog_db=Path("/nonexistent"))
        result = builder.build_from_data(SAMPLE_DATA, output)

        assert result.exists()
        assert result.stat().st_size > 0

    def test_translate_chapter_title(self):
        """Test Chinese chapter title translation."""
        from builders.epub_builder import EpubBuilder

        builder = EpubBuilder(catalog_db=Path("/nonexistent"))

        assert builder._translate_chapter_title("第一回 英雄出世", 1) == "Chapter 1: 英雄出世"
        assert builder._translate_chapter_title("第三十二章 決戰", 32) == "Chapter 32: 決戰"
        assert builder._translate_chapter_title("第廿一回 暗算", 21) == "Chapter 21: 暗算"
        assert builder._translate_chapter_title("", 5) == "Chapter 5"

    def test_parse_chinese_num(self):
        """Test Chinese numeral parsing."""
        from builders.epub_builder import EpubBuilder

        builder = EpubBuilder(catalog_db=Path("/nonexistent"))

        assert builder._parse_chinese_num("一") == 1
        assert builder._parse_chinese_num("十七") == 17
        assert builder._parse_chinese_num("廿一") == 21
        assert builder._parse_chinese_num("卅二") == 32
        assert builder._parse_chinese_num("卌") == 40
        assert builder._parse_chinese_num("") is None


class TestGlossaryRenderer:
    """Test glossary grouping."""

    def test_group_by_category(self):
        """Test that entries are grouped and ordered correctly."""
        from builders.glossary_renderer import group_by_category
        from dataclasses import dataclass

        @dataclass
        class FakeEntry:
            ideogram: str
            pinyin: str
            explanation: str
            category: str
            first_chapter: int = 1

        entries = [
            FakeEntry("劍", "jiàn", "Sword", "Weapons & Equipment", 1),
            FakeEntry("氣", "qì", "Vital energy", "Internal Energy & Cultivation", 2),
            FakeEntry("武當", "Wǔdāng", "Wudang Sect", "Sects & Organizations", 3),
        ]

        groups = group_by_category(entries)

        # Should be ordered by GLOSSARY_CATEGORIES
        keys = list(groups.keys())
        assert keys.index("Internal Energy & Cultivation") < keys.index("Weapons & Equipment")
        assert keys.index("Weapons & Equipment") < keys.index("Sects & Organizations")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
