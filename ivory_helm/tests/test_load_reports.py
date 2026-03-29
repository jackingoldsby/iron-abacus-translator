"""Tests for _load_reports() from ivory_helm/cli/run.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ivory_helm.cli.run import _load_reports


class TestLoadReports:

    def _make_page(self, parent, name, report_data=None):
        page_dir = parent / name
        page_dir.mkdir(parents=True)
        if report_data is not None:
            (page_dir / "iteration_report.json").write_text(
                json.dumps(report_data), encoding="utf-8"
            )
        return page_dir

    def test_empty_directory(self, tmp_path):
        assert _load_reports(tmp_path) == []

    def test_single_volume_with_reports(self, tmp_path):
        vol = tmp_path / "vol1"
        vol.mkdir()
        self._make_page(vol, "page_001", {"page_label": "page_001", "final_status": "pass"})
        self._make_page(vol, "page_002", {"page_label": "page_002", "final_status": "best_effort"})

        reports = _load_reports(tmp_path)
        assert len(reports) == 2
        assert reports[0]["page_label"] == "page_001"
        assert reports[1]["page_label"] == "page_002"

    def test_multi_volume(self, tmp_path):
        for v in ("vol1", "vol2"):
            vol = tmp_path / v
            vol.mkdir()
            self._make_page(vol, "page_001", {"page_label": f"{v}/page_001", "final_status": "pass"})

        reports = _load_reports(tmp_path)
        assert len(reports) == 2
        assert reports[0]["page_label"] == "vol1/page_001"
        assert reports[1]["page_label"] == "vol2/page_001"

    def test_pages_without_report_skipped(self, tmp_path):
        vol = tmp_path / "vol1"
        vol.mkdir()
        self._make_page(vol, "page_001", {"page_label": "page_001", "final_status": "pass"})
        self._make_page(vol, "page_002")  # no report

        reports = _load_reports(tmp_path)
        assert len(reports) == 1
        assert reports[0]["page_label"] == "page_001"
