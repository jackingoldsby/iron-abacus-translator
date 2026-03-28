"""Tests for JSON output contract."""

import pytest

from models.core import Chapter, DetectedWork
from transformers.json_emitter import generate_json


class TestGenerateJson:
    def test_basic_structure(self):
        work = DetectedWork(
            title_simplified="测试书",
            title_traditional="測試書",
            author_simplified="测试作者",
            author_traditional="測試作者",
            chapters=[
                Chapter(title="第一回", content=[{"tag": "p", "content": "内容"}]),
            ],
            character_count=2,
        )
        result = generate_json(work, "A001")

        assert result["metadata"]["title"] == "測試書"
        assert result["metadata"]["creator"] == "測試作者"
        assert result["metadata"]["language"] == "zh-Hant"
        assert result["metadata"]["source"] == "Anna's Archive"
        assert result["metadata"]["publisher"] is None
        assert result["source"] == "A001.epub"
        assert result["number_of_characters"] == 2
        assert len(result["chapters"]) == 1
        assert result["chapters"][0]["title"] == "第一回"
        assert result["chapters"][0]["content"] == [{"tag": "p", "content": "内容"}]

    def test_required_keys_present(self):
        work = DetectedWork(
            title_simplified="x",
            title_traditional="x",
            author_simplified="y",
            author_traditional="y",
            chapters=[],
            character_count=0,
        )
        result = generate_json(work, "A999")

        # Verify all contract-required keys exist
        assert "metadata" in result
        assert "source" in result
        assert "number_of_characters" in result
        assert "chapters" in result
        for key in ("title", "creator", "language", "source", "publisher"):
            assert key in result["metadata"]
