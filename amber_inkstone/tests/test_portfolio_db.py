#!/usr/bin/env python3
"""Tests for portfolio database CRUD operations."""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from catalog.portfolio_db import PortfolioDB
from models.portfolio import ArtworkImage, PeriodResearchResult


def _temp_db():
    """Create a PortfolioDB using a temporary directory (DuckDB needs a fresh path)."""
    tmpdir = tempfile.mkdtemp()
    return PortfolioDB(Path(tmpdir) / "test_portfolio.duckdb")


def test_insert_and_retrieve_image():
    db = _temp_db()
    img = ArtworkImage(
        image_id="abc123",
        period_slug="ming_dynasty",
        period_label="Ming Dynasty",
        source_url="https://example.com/art.jpg",
        source_api="wikimedia_commons",
        title="Mountain Landscape",
        artist="Shen Zhou",
        license="CC0",
        cached_path="/tmp/abc123.jpg",
    )
    db.insert_image(img)

    result = db.get_image("abc123")
    assert result is not None
    assert result.title == "Mountain Landscape"
    assert result.artist == "Shen Zhou"
    assert result.period_slug == "ming_dynasty"


def test_images_by_period():
    db = _temp_db()
    for i, slug in enumerate(["ming_dynasty", "ming_dynasty", "song_dynasty"]):
        db.insert_image(ArtworkImage(
            image_id=f"img_{i}",
            period_slug=slug,
            period_label=slug.replace("_", " ").title(),
            source_url=f"https://example.com/{i}.jpg",
            source_api="met_museum",
            license="CC0",
            cached_path=f"/tmp/img_{i}.jpg",
        ))

    ming = db.get_images_by_period("ming_dynasty")
    assert len(ming) == 2

    song = db.get_images_by_period("song_dynasty")
    assert len(song) == 1


def test_count_by_period():
    db = _temp_db()
    for i in range(3):
        db.insert_image(ArtworkImage(
            image_id=f"m{i}",
            period_slug="ming_dynasty",
            period_label="Ming Dynasty",
            source_url=f"https://example.com/m{i}.jpg",
            source_api="wikimedia_commons",
            license="CC0",
            cached_path=f"/tmp/m{i}.jpg",
        ))
    db.insert_image(ArtworkImage(
        image_id="s0",
        period_slug="song_dynasty",
        period_label="Song Dynasty",
        source_url="https://example.com/s0.jpg",
        source_api="met_museum",
        license="CC0",
        cached_path="/tmp/s0.jpg",
    ))

    counts = db.count_by_period()
    assert counts["ming_dynasty"]["count"] == 3
    assert counts["song_dynasty"]["count"] == 1


def test_assignment_lifecycle():
    db = _temp_db()
    db.insert_image(ArtworkImage(
        image_id="img_001",
        period_slug="ming_dynasty",
        period_label="Ming Dynasty",
        source_url="https://example.com/1.jpg",
        source_api="wikimedia_commons",
        license="CC0",
        cached_path="/tmp/img_001.jpg",
    ))

    # Assign
    db.assign_image("D1379", "img_001")
    a = db.get_assignment("D1379")
    assert a is not None
    assert a.image_id == "img_001"

    # List
    all_a = db.list_assignments()
    assert len(all_a) == 1

    # Clear
    db.clear_assignment("D1379")
    assert db.get_assignment("D1379") is None


def test_research_cache():
    db = _temp_db()
    research = PeriodResearchResult(
        period_slug="song_dynasty",
        period_label="Song Dynasty",
        art_styles=["literati ink wash", "court painting"],
        typical_subjects=["mountain landscape", "birds and flowers"],
        typical_media=["hanging scroll", "handscroll"],
        search_queries=["Ma Yuan landscape", "Song dynasty painting"],
        researched_at=datetime.now(),
    )
    db.cache_research(research)

    cached = db.get_cached_research("song_dynasty")
    assert cached is not None
    assert "literati ink wash" in cached.art_styles
    assert "Ma Yuan landscape" in cached.search_queries
    assert cached.period_label == "Song Dynasty"


def test_upsert_image():
    db = _temp_db()
    img = ArtworkImage(
        image_id="dup1",
        period_slug="ming_dynasty",
        period_label="Ming Dynasty",
        source_url="https://example.com/dup.jpg",
        source_api="wikimedia_commons",
        title="Original Title",
        license="CC0",
        cached_path="/tmp/dup1.jpg",
    )
    db.insert_image(img)

    # Update with same ID
    img.title = "Updated Title"
    db.insert_image(img)

    result = db.get_image("dup1")
    assert result.title == "Updated Title"

    # Should still be just 1 image
    all_ming = db.get_images_by_period("ming_dynasty")
    assert len(all_ming) == 1
