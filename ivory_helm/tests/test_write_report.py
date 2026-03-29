"""Tests for _write_report() from ivory_helm/orchestrator/loop.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class TestWriteReport:

    def _write_report(self, job):
        from ivory_helm.orchestrator.loop import _write_report
        _write_report(job)

    def test_writes_correct_json(self, tmp_path):
        job = {
            "page_dir": tmp_path,
            "page_num": 42,
            "book_id": "test_book",
            "iterations": [{"iteration": 1, "ocr_strips": 10}],
            "final_status": "pass",
        }
        self._write_report(job)

        report_path = tmp_path / "iteration_report.json"
        assert report_path.exists()

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["page_label"] == tmp_path.name
        assert report["page_num"] == 42
        assert report["book_id"] == "test_book"
        assert report["iterations"] == [{"iteration": 1, "ocr_strips": 10}]
        assert report["final_status"] == "pass"

    def test_contains_expected_fields(self, tmp_path):
        job = {
            "page_dir": tmp_path,
            "page_num": 1,
            "book_id": "",
            "iterations": [],
            "final_status": "best_effort",
        }
        self._write_report(job)

        report = json.loads((tmp_path / "iteration_report.json").read_text(encoding="utf-8"))
        expected_keys = {"page_label", "page_num", "book_id", "iterations", "final_status"}
        assert set(report.keys()) == expected_keys
