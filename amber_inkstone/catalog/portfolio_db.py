#!/usr/bin/env python3
"""
Portfolio Database — CRUD operations for artwork_portfolio.duckdb.

Manages artwork_images, artwork_assignments, and period_research_cache tables.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import duckdb

from config.defaults import DEFAULT_PORTFOLIO_DB
from models.portfolio import ArtworkAssignment, ArtworkImage, PeriodResearchResult

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS artwork_images (
    image_id VARCHAR PRIMARY KEY,
    period_slug VARCHAR NOT NULL,
    period_label VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    source_api VARCHAR NOT NULL,
    title VARCHAR,
    artist VARCHAR,
    medium VARCHAR,
    date_text VARCHAR,
    license VARCHAR NOT NULL,
    width INTEGER,
    height INTEGER,
    cached_path VARCHAR NOT NULL,
    thumbnail_path VARCHAR,
    search_query VARCHAR,
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_rating INTEGER,
    user_notes VARCHAR
);

CREATE TABLE IF NOT EXISTS artwork_assignments (
    work_number VARCHAR PRIMARY KEY,
    image_id VARCHAR NOT NULL REFERENCES artwork_images(image_id),
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS period_research_cache (
    period_slug VARCHAR PRIMARY KEY,
    period_label VARCHAR NOT NULL,
    art_styles VARCHAR,
    typical_subjects VARCHAR,
    typical_media VARCHAR,
    search_queries VARCHAR,
    top_themes VARCHAR,
    top_moods VARCHAR,
    century_breakdown VARCHAR,
    thematic_subjects VARCHAR,
    researched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class PortfolioDB:
    """CRUD interface for the artwork portfolio database."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_PORTFOLIO_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path))

    def _ensure_schema(self):
        conn = self._connect()
        conn.execute(_SCHEMA_SQL)
        # Migrate: add thematic columns if missing (existing DBs)
        try:
            cols = {r[0] for r in conn.execute("DESCRIBE period_research_cache").fetchall()}
            for col in ["top_themes", "top_moods", "century_breakdown", "thematic_subjects"]:
                if col not in cols:
                    conn.execute(f"ALTER TABLE period_research_cache ADD COLUMN {col} VARCHAR")
        except Exception:
            pass  # Table may not exist yet on first run
        conn.close()

    # --- Artwork Images ---

    def insert_image(self, img: ArtworkImage) -> None:
        conn = self._connect()
        conn.execute("""
            INSERT OR REPLACE INTO artwork_images
            (image_id, period_slug, period_label, source_url, source_api,
             title, artist, medium, date_text, license,
             width, height, cached_path, thumbnail_path, search_query,
             downloaded_at, user_rating, user_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            img.image_id, img.period_slug, img.period_label,
            img.source_url, img.source_api,
            img.title, img.artist, img.medium, img.date_text, img.license,
            img.width, img.height, img.cached_path, img.thumbnail_path,
            img.search_query,
            img.downloaded_at or datetime.now(),
            img.user_rating, img.user_notes,
        ))
        conn.close()

    def get_images_by_period(self, period_slug: str) -> List[ArtworkImage]:
        conn = self._connect()
        rows = conn.execute("""
            SELECT image_id, period_slug, period_label, source_url, source_api,
                   title, artist, medium, date_text, license,
                   width, height, cached_path, thumbnail_path, search_query,
                   downloaded_at, user_rating, user_notes
            FROM artwork_images
            WHERE period_slug = ?
            ORDER BY downloaded_at DESC
        """, (period_slug,)).fetchall()
        conn.close()
        return [self._row_to_image(r) for r in rows]

    def get_all_images(self) -> List[ArtworkImage]:
        conn = self._connect()
        rows = conn.execute("""
            SELECT image_id, period_slug, period_label, source_url, source_api,
                   title, artist, medium, date_text, license,
                   width, height, cached_path, thumbnail_path, search_query,
                   downloaded_at, user_rating, user_notes
            FROM artwork_images
            ORDER BY period_slug, downloaded_at DESC
        """).fetchall()
        conn.close()
        return [self._row_to_image(r) for r in rows]

    def get_image(self, image_id: str) -> Optional[ArtworkImage]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM artwork_images WHERE image_id = ?", (image_id,)
        ).fetchone()
        conn.close()
        if row:
            return self._row_to_image(row)
        return None

    def count_by_period(self) -> dict:
        """Return {period_slug: count} for all periods with images."""
        conn = self._connect()
        rows = conn.execute("""
            SELECT period_slug, period_label, COUNT(*) as cnt
            FROM artwork_images
            GROUP BY period_slug, period_label
            ORDER BY cnt DESC
        """).fetchall()
        conn.close()
        return {r[0]: {"label": r[1], "count": r[2]} for r in rows}

    @staticmethod
    def _row_to_image(row) -> ArtworkImage:
        return ArtworkImage(
            image_id=row[0], period_slug=row[1], period_label=row[2],
            source_url=row[3], source_api=row[4],
            title=row[5] or "", artist=row[6] or "",
            medium=row[7] or "", date_text=row[8] or "",
            license=row[9] or "",
            width=row[10] or 0, height=row[11] or 0,
            cached_path=row[12] or "", thumbnail_path=row[13] or "",
            search_query=row[14] or "",
            downloaded_at=row[15], user_rating=row[16],
            user_notes=row[17] or "",
        )

    # --- Artwork Assignments ---

    def assign_image(self, work_number: str, image_id: str) -> None:
        conn = self._connect()
        conn.execute("""
            INSERT OR REPLACE INTO artwork_assignments
            (work_number, image_id, assigned_at)
            VALUES (?, ?, ?)
        """, (work_number, image_id, datetime.now()))
        conn.close()

    def clear_assignment(self, work_number: str) -> bool:
        conn = self._connect()
        result = conn.execute(
            "DELETE FROM artwork_assignments WHERE work_number = ?",
            (work_number,)
        )
        deleted = result.fetchone() is not None  # DuckDB returns differently
        conn.close()
        return True

    def get_assignment(self, work_number: str) -> Optional[ArtworkAssignment]:
        conn = self._connect()
        row = conn.execute(
            "SELECT work_number, image_id, assigned_at FROM artwork_assignments WHERE work_number = ?",
            (work_number,)
        ).fetchone()
        conn.close()
        if row:
            return ArtworkAssignment(work_number=row[0], image_id=row[1], assigned_at=row[2])
        return None

    def list_assignments(self) -> List[ArtworkAssignment]:
        conn = self._connect()
        rows = conn.execute("""
            SELECT a.work_number, a.image_id, a.assigned_at
            FROM artwork_assignments a
            ORDER BY a.assigned_at DESC
        """).fetchall()
        conn.close()
        return [ArtworkAssignment(work_number=r[0], image_id=r[1], assigned_at=r[2]) for r in rows]

    # --- Period Research Cache ---

    def cache_research(self, result: PeriodResearchResult) -> None:
        conn = self._connect()
        conn.execute("""
            INSERT OR REPLACE INTO period_research_cache
            (period_slug, period_label, art_styles, typical_subjects,
             typical_media, search_queries, top_themes, top_moods,
             century_breakdown, thematic_subjects, researched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.period_slug, result.period_label,
            json.dumps(result.art_styles),
            json.dumps(result.typical_subjects),
            json.dumps(result.typical_media),
            json.dumps(result.search_queries),
            json.dumps(result.top_themes),
            json.dumps(result.top_moods),
            json.dumps(result.century_breakdown),
            json.dumps(result.thematic_subjects),
            result.researched_at or datetime.now(),
        ))
        conn.close()

    def get_cached_research(self, period_slug: str) -> Optional[PeriodResearchResult]:
        conn = self._connect()
        row = conn.execute(
            "SELECT period_slug, period_label, art_styles, typical_subjects, "
            "typical_media, search_queries, top_themes, top_moods, "
            "century_breakdown, thematic_subjects, researched_at "
            "FROM period_research_cache WHERE period_slug = ?",
            (period_slug,)
        ).fetchone()
        conn.close()
        if row:
            return PeriodResearchResult(
                period_slug=row[0], period_label=row[1],
                art_styles=json.loads(row[2] or "[]"),
                typical_subjects=json.loads(row[3] or "[]"),
                typical_media=json.loads(row[4] or "[]"),
                search_queries=json.loads(row[5] or "[]"),
                top_themes=json.loads(row[6] or "[]"),
                top_moods=json.loads(row[7] or "[]"),
                century_breakdown=json.loads(row[8] or "{}"),
                thematic_subjects=json.loads(row[9] or "[]"),
                researched_at=row[10],
            )
        return None
