"""Tests for preflight checks and progress tracking."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ivory_helm.orchestrator.loop import _preflight_check, _write_progress


def _make_page_dirs(tmp_path: Path, with_detection: bool = True) -> Path:
    """Create a strips dir with one page directory."""
    page_dir = tmp_path / "page_001"
    page_dir.mkdir()
    if with_detection:
        (page_dir / "detection.json").write_text('{"source_pdf": "test.pdf"}')
    return tmp_path


def _mock_bronze_mirror():
    """Create a mock bronze_mirror module with OcrEngine."""
    mock_engine = MagicMock()
    mock_module = MagicMock()
    mock_module.OcrEngine = MagicMock(return_value=mock_engine)

    # Ensure the module is importable
    mock_parent = MagicMock()
    mock_ocr = MagicMock()
    mock_ocr.paddle_engine = mock_module

    return mock_engine, {
        "bronze_mirror": mock_parent,
        "bronze_mirror.ocr": mock_ocr,
        "bronze_mirror.ocr.paddle_engine": mock_module,
    }


def test_missing_api_key(tmp_path, monkeypatch):
    """Missing OPENAI_API_KEY should appear in error message."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    strips_dir = _make_page_dirs(tmp_path, with_detection=True)

    _engine, modules = _mock_bronze_mirror()
    with patch.dict(sys.modules, modules):
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            _preflight_check(strips_dir)


def test_no_page_dirs(tmp_path, monkeypatch):
    """Empty strips dir should fail with 'No page directories'."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    _engine, modules = _mock_bronze_mirror()
    with patch.dict(sys.modules, modules):
        with pytest.raises(RuntimeError, match="No page directories"):
            _preflight_check(tmp_path)


def test_no_detection_json(tmp_path, monkeypatch):
    """Page dir without detection.json should fail."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    strips_dir = _make_page_dirs(tmp_path, with_detection=False)

    _engine, modules = _mock_bronze_mirror()
    with patch.dict(sys.modules, modules):
        with pytest.raises(RuntimeError, match="detection.json"):
            _preflight_check(strips_dir)


def test_preflight_passes(tmp_path, monkeypatch):
    """All checks pass — returns (page_count, engine)."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    strips_dir = _make_page_dirs(tmp_path, with_detection=True)
    # Add a second page
    page2 = tmp_path / "page_002"
    page2.mkdir()
    (page2 / "detection.json").write_text("{}")

    mock_engine, modules = _mock_bronze_mirror()

    mock_openai_client = MagicMock()
    mock_openai_cls = MagicMock(return_value=mock_openai_client)

    with patch.dict(sys.modules, modules):
        with patch("openai.OpenAI", mock_openai_cls):
            page_count, engine = _preflight_check(strips_dir)

    assert page_count == 2
    assert engine is mock_engine


def test_write_progress(tmp_path):
    """progress.json should be valid JSON with correct keys."""
    _write_progress(tmp_path, "三俠五義", "running",
                    round_num=2, total_pages=100, passed=80, pending=20)

    progress_path = tmp_path / "progress.json"
    assert progress_path.exists()

    data = json.loads(progress_path.read_text())
    assert data["book_id"] == "三俠五義"
    assert data["status"] == "running"
    assert data["round"] == 2
    assert data["total_pages"] == 100
    assert data["passed"] == 80
    assert data["pending"] == 20
    assert "updated" in data
    assert "error" not in data


def test_write_progress_error(tmp_path):
    """Error progress should include error field."""
    _write_progress(tmp_path, "三俠五義", "error",
                    total_pages=100, passed=50, pending=50,
                    error="Traceback: something broke")

    data = json.loads((tmp_path / "progress.json").read_text())
    assert data["status"] == "error"
    assert "something broke" in data["error"]
