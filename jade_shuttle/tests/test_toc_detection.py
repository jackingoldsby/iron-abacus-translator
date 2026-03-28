"""Tests for TOC detection logic."""

import pytest

from detectors.toc_detector import is_generic_volume_title


class TestIsGenericVolumeTitle:
    def test_numbered_volume(self):
        assert is_generic_volume_title("第一卷") is True
        assert is_generic_volume_title("第二册") is True

    def test_numbered_volume_with_subtitle(self):
        assert is_generic_volume_title("第一卷 魔女国") is True

    def test_positional_volume(self):
        assert is_generic_volume_title("上卷") is True
        assert is_generic_volume_title("下册") is True
        assert is_generic_volume_title("中") is True

    def test_actual_work_title(self):
        assert is_generic_volume_title("寻秦记") is False
        assert is_generic_volume_title("白发魔女传") is False

    def test_work_title_with_volume(self):
        # These contain volume markers but are NOT generic volume titles
        assert is_generic_volume_title("寻秦记·第一册") is False
