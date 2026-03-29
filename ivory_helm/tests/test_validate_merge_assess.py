"""Tests for _validate_merge_assess() from ivory_helm/orchestrator/loop.py."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ivory_helm.config.book_config import BookConfig, IvoryHelmConfig


def _make_cfg():
    return BookConfig(ivory_helm=IvoryHelmConfig(
        min_kept_ratio=0.5, min_chars_per_page=30, max_empty_strips=2,
    ))


def _setup_page_files(page_dir, validation=None, merged=None):
    """Write validation.json and ocr_merged.json for _assess_page."""
    if validation is not None:
        (page_dir / "validation.json").write_text(
            json.dumps(validation), encoding="utf-8"
        )
    if merged is not None:
        (page_dir / "ocr_merged.json").write_text(
            json.dumps(merged), encoding="utf-8"
        )


class TestValidateMergeAssess:

    def _run(self, job, validate_page, merge_page, cfg=None):
        from ivory_helm.orchestrator.loop import _validate_merge_assess
        asyncio.run(_validate_merge_assess(
            job,
            nano_client=Mock(),
            nano_semaphore=asyncio.Semaphore(10),
            cfg=cfg or _make_cfg(),
            validate_page=validate_page,
            merge_page=merge_page,
        ))

    def test_passed_assessment(self, tmp_path):
        _setup_page_files(
            tmp_path,
            validation={"validated": 10, "kept": 8, "strips": []},
            merged={"total_chars": 200},
        )

        async def mock_validate(page_dir, client, sem):
            return {"kept": 8, "excluded": 2}

        def mock_merge(page_dir):
            pass  # files already written

        job = {
            "page_dir": tmp_path,
            "iterations": [{"iteration": 1}],
        }
        self._run(job, AsyncMock(side_effect=mock_validate), mock_merge)
        assert job["_round_passed"] is True
        assert job["iterations"][0]["kept"] == 8
        assert job["iterations"][0]["excluded"] == 2

    def test_failed_assessment(self, tmp_path):
        _setup_page_files(
            tmp_path,
            validation={"validated": 10, "kept": 2, "strips": []},
            merged={"total_chars": 5},
        )

        async def mock_validate(page_dir, client, sem):
            return {"kept": 2, "excluded": 8}

        job = {
            "page_dir": tmp_path,
            "iterations": [{"iteration": 1}],
        }
        self._run(job, AsyncMock(side_effect=mock_validate), Mock())
        assert job["_round_passed"] is False

    def test_calls_validate_then_merge_then_assess(self, tmp_path):
        call_order = []

        _setup_page_files(
            tmp_path,
            validation={"validated": 10, "kept": 8, "strips": []},
            merged={"total_chars": 100},
        )

        async def mock_validate(page_dir, client, sem):
            call_order.append("validate")
            return {"kept": 8, "excluded": 2}

        def mock_merge(page_dir):
            call_order.append("merge")

        job = {
            "page_dir": tmp_path,
            "iterations": [{"iteration": 1}],
        }
        self._run(job, AsyncMock(side_effect=mock_validate), mock_merge)
        assert call_order == ["validate", "merge"]
        # assess runs after merge (evidenced by _round_passed being set)
        assert "_round_passed" in job
