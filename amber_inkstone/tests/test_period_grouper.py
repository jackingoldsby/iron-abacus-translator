#!/usr/bin/env python3
"""Tests for period grouper and dynasty normalization."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.dynasty_periods import normalize_period, get_whitelisted_artists
from catalog.theme_extractor import _extract_centuries, _map_themes_to_subjects, _split_field, THEME_SUBJECT_MAP


def test_normalize_basic_dynasties():
    assert normalize_period("Ming Dynasty") == ("ming_dynasty", "Ming Dynasty")
    assert normalize_period("Song Dynasty") == ("song_dynasty", "Song Dynasty")
    assert normalize_period("Qing Dynasty") == ("qing_dynasty", "Qing Dynasty")
    assert normalize_period("Tang Dynasty") == ("tang_dynasty", "Tang Dynasty")
    assert normalize_period("Yuan Dynasty") == ("yuan_dynasty", "Yuan Dynasty")


def test_normalize_with_qualifiers():
    slug, label = normalize_period("Ming Dynasty (implied)")
    assert slug == "ming_dynasty"
    assert label == "Ming Dynasty"

    slug, label = normalize_period("Late Ming Dynasty")
    assert slug == "ming_dynasty"
    assert label == "Ming Dynasty"

    slug, label = normalize_period("Ming Dynasty (implied jianghu setting)")
    assert slug == "ming_dynasty"
    assert label == "Ming Dynasty"


def test_normalize_compound_periods():
    slug, _ = normalize_period("Song-Yuan dynasties (12th-14th century)")
    assert slug == "song_dynasty"  # First match wins

    slug, _ = normalize_period("Tang dynasty (8th century, An Lushan Rebellion)")
    assert slug == "tang_dynasty"

    slug, _ = normalize_period("Late Eastern Han Dynasty, Three Kingdoms period")
    # "three kingdoms" comes before "han" in keyword order
    assert slug == "three_kingdoms"


def test_normalize_unspecified():
    for text in [
        "Jianghu world",
        "Not specific / Jianghu period",
        "Unspecified historical period (classic wuxia setting).",
        "Fantasy ancient China, mythical era.",
        "",
        None,
    ]:
        slug, label = normalize_period(text or "")
        assert slug == "unspecified"
        assert label == "Unspecified Period"


def test_normalize_case_insensitive():
    slug, _ = normalize_period("MING DYNASTY")
    assert slug == "ming_dynasty"

    slug, _ = normalize_period("qing dynasty")
    assert slug == "qing_dynasty"


def test_whitelisted_artists():
    artists = get_whitelisted_artists("song_dynasty")
    assert "Ma Yuan" in artists
    assert "Fan Kuan" in artists

    artists = get_whitelisted_artists("ming_dynasty")
    assert "Tang Yin" in artists
    assert "Shen Zhou" in artists

    assert get_whitelisted_artists("unknown_period") == []


def test_normalize_republic():
    slug, label = normalize_period("Republic era setting")
    assert slug == "republic_era"
    assert label == "Republic Era"


# --- Theme extractor tests ---

def test_extract_centuries_single():
    assert _extract_centuries("Ming Dynasty (15th century)") == ["15th century"]


def test_extract_centuries_range():
    result = _extract_centuries("Song-Yuan dynasties (12th-14th century)")
    assert result == ["12th century", "13th century", "14th century"]


def test_extract_centuries_slash():
    result = _extract_centuries("Qing Dynasty, late 18th/early 19th century")
    assert "18th century" in result
    assert "19th century" in result


def test_extract_centuries_none():
    assert _extract_centuries("Ming Dynasty") == []
    assert _extract_centuries("") == []
    assert _extract_centuries(None) == []


def test_extract_centuries_with_qualifier():
    result = _extract_centuries("Tang dynasty (8th century, An Lushan Rebellion)")
    assert result == ["8th century"]


def test_split_field():
    assert _split_field("romance, revenge, political intrigue") == [
        "romance", "revenge", "political intrigue"
    ]
    assert _split_field("epic; melancholy; romantic") == [
        "epic", "melancholy", "romantic"
    ]
    assert _split_field("love and betrayal") == ["love", "betrayal"]
    assert _split_field("") == []
    assert _split_field(None) == []


def test_map_themes_to_subjects():
    subjects = _map_themes_to_subjects(["romance", "martial arts", "revenge"])
    assert any("couple" in s or "lovers" in s for s in subjects)
    assert any("warrior" in s or "combat" in s for s in subjects)


def test_map_themes_no_match():
    subjects = _map_themes_to_subjects(["something completely unrelated"])
    assert subjects == []


def test_theme_subject_map_completeness():
    """Ensure the mapping covers major wuxia themes."""
    expected_keys = ["romance", "revenge", "martial arts", "political intrigue",
                     "brotherhood", "forbidden love"]
    for key in expected_keys:
        assert key in THEME_SUBJECT_MAP, f"Missing theme mapping: {key}"
