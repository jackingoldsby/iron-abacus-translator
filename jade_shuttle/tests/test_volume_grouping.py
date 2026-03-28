"""Tests for volume grouping logic."""

import pytest

from detectors.volume_grouper import strip_volume_marker


class TestStripVolumeMarker:
    def test_parenthesized_upper(self):
        base, marker = strip_volume_marker("七剑下天山（上册）")
        assert base == "七剑下天山"
        assert marker == "（上册）"

    def test_parenthesized_middle(self):
        base, marker = strip_volume_marker("江湖三女侠（中册）")
        assert base == "江湖三女侠"

    def test_suffix_upper(self):
        base, marker = strip_volume_marker("白发魔女传上册")
        assert base == "白发魔女传"

    def test_arabic_numeral(self):
        base, marker = strip_volume_marker("风尘侠隐鹰爪王10")
        assert base == "风尘侠隐鹰爪王"
        assert marker == "10"

    def test_chinese_numeral(self):
        base, marker = strip_volume_marker("荒江女侠十七")
        assert base == "荒江女侠"

    def test_no_marker(self):
        base, marker = strip_volume_marker("白发魔女传")
        assert base == "白发魔女传"
        assert marker == ""

    def test_dot_volume(self):
        base, marker = strip_volume_marker("天地明环·卷二")
        assert base == "天地明环"
