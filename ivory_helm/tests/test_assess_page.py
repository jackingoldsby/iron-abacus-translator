"""Tests for _assess_page() from ivory_helm/orchestrator/loop.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ivory_helm.config.book_config import BookConfig, IvoryHelmConfig


class TestAssessPage:
    """Unit tests for _assess_page quality gate."""

    def _make_cfg(self, **overrides) -> BookConfig:
        ih_kwargs = {
            "min_kept_ratio": 0.5,
            "min_chars_per_page": 30,
            "max_empty_strips": 2,
        }
        ih_kwargs.update(overrides)
        return BookConfig(ivory_helm=IvoryHelmConfig(**ih_kwargs))

    def _write_validation(self, page_dir, validated=10, kept=8, strips=None):
        data = {"validated": validated, "kept": kept, "strips": strips or []}
        (page_dir / "validation.json").write_text(json.dumps(data), encoding="utf-8")

    def _write_merged(self, page_dir, total_chars=100):
        data = {"total_chars": total_chars}
        (page_dir / "ocr_merged.json").write_text(json.dumps(data), encoding="utf-8")

    def _assess(self, page_dir, cfg=None):
        # Import here to avoid cv2 at module level
        from ivory_helm.orchestrator.loop import _assess_page
        return _assess_page(page_dir, cfg or self._make_cfg())

    def test_all_thresholds_pass(self, tmp_path):
        self._write_validation(tmp_path, validated=10, kept=8)
        self._write_merged(tmp_path, total_chars=100)
        result = self._assess(tmp_path)
        assert result["pass"] is True
        assert result["reason"] == "ok"
        assert result["kept_ratio"] == 0.8
        assert result["total_chars"] == 100

    def test_low_kept_ratio_fails(self, tmp_path):
        self._write_validation(tmp_path, validated=10, kept=3)
        self._write_merged(tmp_path, total_chars=100)
        result = self._assess(tmp_path)
        assert result["pass"] is False
        assert "kept_ratio=0.30 < 0.5" in result["reason"]

    def test_low_char_count_fails(self, tmp_path):
        self._write_validation(tmp_path, validated=10, kept=8)
        self._write_merged(tmp_path, total_chars=10)
        result = self._assess(tmp_path)
        assert result["pass"] is False
        assert "chars=10 < 30" in result["reason"]

    def test_too_many_empty_strips_fails(self, tmp_path):
        strips = [
            {"nano_classification": "blank", "status": "excluded"},
            {"nano_classification": "blank", "status": "excluded"},
            {"nano_classification": "blank", "status": "excluded"},
        ]
        self._write_validation(tmp_path, validated=10, kept=7, strips=strips)
        self._write_merged(tmp_path, total_chars=100)
        result = self._assess(tmp_path)
        assert result["pass"] is False
        assert "empty_strips=3 > 2" in result["reason"]

    def test_multiple_failures_joined(self, tmp_path):
        strips = [
            {"nano_classification": "blank", "status": "excluded"},
            {"nano_classification": "blank", "status": "excluded"},
            {"nano_classification": "blank", "status": "excluded"},
        ]
        self._write_validation(tmp_path, validated=10, kept=3, strips=strips)
        self._write_merged(tmp_path, total_chars=5)
        result = self._assess(tmp_path)
        assert result["pass"] is False
        parts = result["reason"].split("; ")
        assert len(parts) == 3

    def test_missing_validation_json(self, tmp_path):
        result = self._assess(tmp_path)
        assert result["pass"] is False
        assert result["reason"] == "no_validation"

    def test_missing_ocr_merged_json(self, tmp_path):
        self._write_validation(tmp_path, validated=10, kept=8)
        # No ocr_merged.json → total_chars=0
        result = self._assess(tmp_path)
        assert result["pass"] is False
        assert result["total_chars"] == 0
        assert "chars=0 < 30" in result["reason"]

    def test_zero_total_strips(self, tmp_path):
        self._write_validation(tmp_path, validated=0, kept=0)
        self._write_merged(tmp_path, total_chars=0)
        result = self._assess(tmp_path)
        assert result["kept_ratio"] == 0
        # zero total means kept_ratio check is skipped (total > 0 guard)
        # but chars=0 still fails
        assert result["pass"] is False

    def test_pass_through_strips_not_counted_as_empty(self, tmp_path):
        strips = [
            {"nano_classification": "blank", "status": "pass_through"},
            {"nano_classification": "blank", "status": "pass_through"},
            {"nano_classification": "blank", "status": "pass_through"},
        ]
        self._write_validation(tmp_path, validated=10, kept=8, strips=strips)
        self._write_merged(tmp_path, total_chars=100)
        result = self._assess(tmp_path)
        # pass_through blanks don't count as empty
        assert result["empty_strips"] == 0
        assert result["pass"] is True
