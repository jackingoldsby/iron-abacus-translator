#!/usr/bin/env python3
"""
Glossary Deduplication Script

Merges translation glossary CSV and candidate terms CSV,
resolving duplicates and conflicts, then exports to SQLite database.

Usage:
    python scripts/deduplicate_glossary.py \\
        --glossary translation_glossary.csv \\
        --candidates candidate_terms.csv \\
        --output glossary_merged.csv \\
        --db glossary.db \\
        --report deduplication_report.json
"""

import argparse
import csv
import json
from utils.db import connect_glossary
import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class GlossaryEntry:
    """Unified glossary entry"""
    chinese: str
    pinyin: str
    translation_strategy: str  # PINYIN_ONLY, ENGLISH_ONLY, HYBRID
    recommended_form: str
    footnote_template: str
    category: str
    rationale: str
    deduplication_strategy: str  # FIRST_OCCURRENCE_ONLY, RECURRING_BRIEF, EVERY_OCCURRENCE
    expected_frequency: str  # VERY_HIGH, HIGH, MEDIUM, LOW, RARE
    source: str  # glossary, candidates, both

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class DeduplicationReport:
    """Report of deduplication process"""
    total_glossary_entries: int
    total_candidate_entries: int
    unique_chinese_terms: int
    duplicates_found: int
    conflicts_resolved: int
    merged_entries: int
    glossary_priority: int
    candidate_additions: int
    conflicts: List[Dict]

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)


# =============================================================================
# DEDUPLICATION ENGINE
# =============================================================================

class GlossaryDeduplicator:
    """
    Deduplicates and merges glossary entries.

    Strategy:
    1. Load both CSV files
    2. Index by Chinese term
    3. Resolve duplicates (glossary takes priority)
    4. Flag conflicts for review
    5. Export merged results to CSV and SQLite
    """

    def __init__(self):
        self.glossary_entries: Dict[str, GlossaryEntry] = {}
        self.candidate_entries: Dict[str, GlossaryEntry] = {}
        self.merged_entries: Dict[str, GlossaryEntry] = {}
        self.conflicts: List[Dict] = []

    def load_glossary_csv(self, filepath: Path) -> None:
        """
        Load main glossary CSV (authoritative source).

        Format:
        Chinese,Pinyin,Translation_Strategy,Recommended_Form,Footnote_Template,
        Category,Rationale,Deduplication_Strategy,Expected_Frequency
        """
        logger.info(f"Loading main glossary from {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                entry = GlossaryEntry(
                    chinese=row['Chinese'].strip(),
                    pinyin=row['Pinyin'].strip(),
                    translation_strategy=row['Translation_Strategy'].strip(),
                    recommended_form=row['Recommended_Form'].strip(),
                    footnote_template=row['Footnote_Template'].strip(),
                    category=row['Category'].strip(),
                    rationale=row['Rationale'].strip(),
                    deduplication_strategy=row['Deduplication_Strategy'].strip(),
                    expected_frequency=row['Expected_Frequency'].strip(),
                    source='glossary'
                )
                self.glossary_entries[entry.chinese] = entry

        logger.info(f"Loaded {len(self.glossary_entries)} entries from main glossary")

    def load_candidates_csv(self, filepath: Path) -> None:
        """
        Load candidate terms CSV.

        Format:
        Chinese,Pinyin,Translation,Explanation

        Will need to infer missing fields based on heuristics.
        """
        logger.info(f"Loading candidate terms from {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                chinese = row['Chinese'].strip()
                pinyin = row['Pinyin'].strip()
                translation = row['Translation'].strip()
                explanation = row['Explanation'].strip()

                # Infer translation strategy
                strategy = self._infer_translation_strategy(chinese, pinyin, translation)

                # Build recommended form
                recommended_form = self._build_recommended_form(strategy, pinyin, translation)

                # Build footnote template
                footnote_template = f"{translation} ({chinese} *{pinyin}*): {explanation}"

                # Infer category
                category = self._infer_category(chinese, translation, explanation)

                # Default deduplication strategy
                dedup_strategy = "FIRST_OCCURRENCE_ONLY"

                # Infer frequency
                frequency = self._infer_frequency(category)

                entry = GlossaryEntry(
                    chinese=chinese,
                    pinyin=pinyin,
                    translation_strategy=strategy,
                    recommended_form=recommended_form,
                    footnote_template=footnote_template,
                    category=category,
                    rationale=f"Inferred from candidate terms: {explanation}",
                    deduplication_strategy=dedup_strategy,
                    expected_frequency=frequency,
                    source='candidates'
                )
                self.candidate_entries[chinese] = entry

        logger.info(f"Loaded {len(self.candidate_entries)} entries from candidates")

    def _infer_translation_strategy(self, chinese: str, pinyin: str, translation: str) -> str:
        """
        Infer translation strategy from available data.

        Heuristics:
        - If translation is just pinyin → PINYIN_ONLY
        - If translation contains pinyin → HYBRID
        - Otherwise → ENGLISH_ONLY
        """
        translation_lower = translation.lower()
        pinyin_normalized = pinyin.replace(' ', '').lower()

        # Check if translation is essentially the pinyin
        if translation_lower == pinyin_normalized or translation_lower == pinyin.lower():
            return "PINYIN_ONLY"

        # Check if translation contains pinyin
        if pinyin_normalized in translation_lower.replace(' ', ''):
            return "HYBRID"

        return "ENGLISH_ONLY"

    def _build_recommended_form(self, strategy: str, pinyin: str, translation: str) -> str:
        """Build recommended form based on strategy"""
        if strategy == "PINYIN_ONLY":
            return f"*{pinyin}*"
        elif strategy == "HYBRID":
            # Extract English part if possible
            return translation
        else:
            return translation

    def _infer_category(self, chinese: str, translation: str, explanation: str) -> str:
        """
        Infer category from term characteristics.

        Categories: technique_category, concept, anatomy, pathology, technique,
        tier, doctrine, style, weapon, organization, title, rank, faction,
        social_class, relationship, address, archetype, profession, ethics,
        social, substance, principle, action, metaphor, measurement, general,
        technique_named, world, practice, state, object
        """
        # Keywords for categorization
        keywords = {
            'technique_category': ['法', '功', '術', '技'],
            'concept': ['氣', '力', '神', '心'],
            'anatomy': ['經', '脈', '穴', '田'],
            'pathology': ['傷', '痛', '病', '症'],
            'organization': ['門', '派', '舵', '堂'],
            'title': ['主', '長', '師', '護'],
            'relationship': ['兄', '弟', '姐', '妹', '師', '徒'],
            'weapon': ['劍', '刀', '槍', '棍', '鞭'],
            'ethics': ['義', '德', '恩', '怨'],
            'substance': ['丹', '藥', '毒']
        }

        # Check Chinese characters for keywords
        for category, chars in keywords.items():
            if any(char in chinese for char in chars):
                return category

        # Default to 'concept'
        return 'concept'

    def _infer_frequency(self, category: str) -> str:
        """Infer expected frequency from category"""
        high_frequency_categories = {
            'concept', 'technique_category', 'relationship', 'general'
        }

        if category in high_frequency_categories:
            return 'HIGH'
        else:
            return 'MEDIUM'

    def merge_entries(self) -> None:
        """
        Merge glossary and candidate entries.

        Strategy:
        1. Start with all glossary entries (authoritative)
        2. Add candidate entries not in glossary
        3. Flag duplicates/conflicts for review
        """
        logger.info("Merging entries...")

        # Start with glossary (authoritative)
        self.merged_entries = dict(self.glossary_entries)
        glossary_priority = len(self.glossary_entries)

        # Process candidates
        candidate_additions = 0
        duplicates_found = 0
        conflicts_resolved = 0

        for chinese, candidate_entry in self.candidate_entries.items():
            if chinese in self.merged_entries:
                # Duplicate found
                duplicates_found += 1
                glossary_entry = self.merged_entries[chinese]

                # Check if there are significant differences
                conflict = self._detect_conflict(glossary_entry, candidate_entry)

                if conflict:
                    self.conflicts.append({
                        'chinese': chinese,
                        'glossary': glossary_entry.to_dict(),
                        'candidate': candidate_entry.to_dict(),
                        'differences': conflict
                    })
                    conflicts_resolved += 1
                    logger.warning(f"Conflict detected for '{chinese}': {conflict}")

                # Glossary takes priority, keep existing
                # Mark as appearing in both sources
                self.merged_entries[chinese].source = 'both'
            else:
                # New entry from candidates
                self.merged_entries[chinese] = candidate_entry
                candidate_additions += 1

        # Generate report
        self.report = DeduplicationReport(
            total_glossary_entries=len(self.glossary_entries),
            total_candidate_entries=len(self.candidate_entries),
            unique_chinese_terms=len(self.merged_entries),
            duplicates_found=duplicates_found,
            conflicts_resolved=conflicts_resolved,
            merged_entries=len(self.merged_entries),
            glossary_priority=glossary_priority,
            candidate_additions=candidate_additions,
            conflicts=self.conflicts
        )

        logger.info(f"Merge complete:")
        logger.info(f"  - Glossary entries: {self.report.total_glossary_entries}")
        logger.info(f"  - Candidate entries: {self.report.total_candidate_entries}")
        logger.info(f"  - Unique terms: {self.report.unique_chinese_terms}")
        logger.info(f"  - Duplicates: {self.report.duplicates_found}")
        logger.info(f"  - Conflicts: {self.report.conflicts_resolved}")
        logger.info(f"  - New from candidates: {self.report.candidate_additions}")

    def _detect_conflict(self, glossary: GlossaryEntry, candidate: GlossaryEntry) -> Optional[List[str]]:
        """
        Detect significant differences between entries.

        Returns list of conflicting fields, or None if no conflicts.
        """
        conflicts = []

        # Check pinyin
        if glossary.pinyin.lower() != candidate.pinyin.lower():
            conflicts.append(f"pinyin: '{glossary.pinyin}' vs '{candidate.pinyin}'")

        # Check translation strategy (not critical, just note)
        if glossary.translation_strategy != candidate.translation_strategy:
            conflicts.append(f"strategy: '{glossary.translation_strategy}' vs '{candidate.translation_strategy}'")

        # Check category (not critical)
        if glossary.category != candidate.category:
            conflicts.append(f"category: '{glossary.category}' vs '{candidate.category}'")

        return conflicts if conflicts else None

    def export_to_csv(self, output_path: Path) -> None:
        """Export merged entries to CSV"""
        logger.info(f"Exporting to CSV: {output_path}")

        fieldnames = [
            'Chinese', 'Pinyin', 'Translation_Strategy', 'Recommended_Form',
            'Footnote_Template', 'Category', 'Rationale', 'Deduplication_Strategy',
            'Expected_Frequency', 'Source'
        ]

        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for entry in sorted(self.merged_entries.values(), key=lambda e: e.chinese):
                writer.writerow({
                    'Chinese': entry.chinese,
                    'Pinyin': entry.pinyin,
                    'Translation_Strategy': entry.translation_strategy,
                    'Recommended_Form': entry.recommended_form,
                    'Footnote_Template': entry.footnote_template,
                    'Category': entry.category,
                    'Rationale': entry.rationale,
                    'Deduplication_Strategy': entry.deduplication_strategy,
                    'Expected_Frequency': entry.expected_frequency,
                    'Source': entry.source
                })

        logger.info(f"Exported {len(self.merged_entries)} entries to {output_path}")

    def export_to_db(self, db_path: Path) -> None:
        """
        Export merged entries to DuckDB database.

        Schema:
        CREATE TABLE glossary (
            id INTEGER PRIMARY KEY,
            chinese VARCHAR UNIQUE NOT NULL,
            pinyin VARCHAR NOT NULL,
            translation_strategy VARCHAR NOT NULL,
            recommended_form VARCHAR NOT NULL,
            footnote_template VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            rationale VARCHAR,
            deduplication_strategy VARCHAR NOT NULL,
            expected_frequency VARCHAR NOT NULL,
            source VARCHAR NOT NULL
        );
        """
        import duckdb
        logger.info(f"Exporting to DuckDB: {db_path}")

        conn = duckdb.connect(str(db_path))

        # Drop existing table if present
        conn.execute("DROP TABLE IF EXISTS glossary")

        # Create table
        conn.execute("""
            CREATE TABLE glossary (
                id INTEGER PRIMARY KEY,
                chinese VARCHAR UNIQUE NOT NULL,
                pinyin VARCHAR NOT NULL,
                translation_strategy VARCHAR NOT NULL,
                recommended_form VARCHAR NOT NULL,
                footnote_template VARCHAR NOT NULL,
                category VARCHAR NOT NULL,
                rationale VARCHAR,
                deduplication_strategy VARCHAR NOT NULL,
                expected_frequency VARCHAR NOT NULL,
                source VARCHAR NOT NULL
            )
        """)

        # Insert entries using sequence for id
        conn.execute("CREATE SEQUENCE IF NOT EXISTS glossary_id_seq START 1")
        for entry in self.merged_entries.values():
            conn.execute("""
                INSERT INTO glossary
                (id, chinese, pinyin, translation_strategy, recommended_form,
                 footnote_template, category, rationale, deduplication_strategy,
                 expected_frequency, source)
                VALUES (nextval('glossary_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.chinese,
                entry.pinyin,
                entry.translation_strategy,
                entry.recommended_form,
                entry.footnote_template,
                entry.category,
                entry.rationale,
                entry.deduplication_strategy,
                entry.expected_frequency,
                entry.source,
            ))

        conn.close()

        logger.info(f"Exported {len(self.merged_entries)} entries to DuckDB")

    def save_report(self, report_path: Path) -> None:
        """Save deduplication report as JSON"""
        logger.info(f"Saving report to {report_path}")

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(self.report.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"Report saved to {report_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Deduplicate and merge glossary entries"
    )
    parser.add_argument(
        '--glossary',
        type=Path,
        default=Path('data/glossaries/wuxia_translation_glossary.csv'),
        help='Path to main glossary CSV (authoritative)'
    )
    parser.add_argument(
        '--candidates',
        type=Path,
        default=Path('data/glossaries/candidate_wuxia_terms.csv'),
        help='Path to candidate terms CSV'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('data/glossaries/glossary_merged.csv'),
        help='Output path for merged CSV'
    )
    parser.add_argument(
        '--db',
        type=Path,
        default=None,
        help='Output path for glossary DuckDB (default: from environment config)'
    )
    parser.add_argument(
        '--report',
        type=Path,
        default=Path('data/analysis/deduplication_report.json'),
        help='Output path for deduplication report'
    )

    args = parser.parse_args()

    try:
        # Initialize deduplicator
        deduplicator = GlossaryDeduplicator()

        # Load data
        deduplicator.load_glossary_csv(args.glossary)
        deduplicator.load_candidates_csv(args.candidates)

        # Merge
        deduplicator.merge_entries()

        # Resolve DB path
        db_path = args.db
        if db_path is None:
            from utils.environment_config import get_or_create_config
            db_path = get_or_create_config().glossary_path

        # Export
        deduplicator.export_to_csv(args.output)
        deduplicator.export_to_db(db_path)
        deduplicator.save_report(args.report)

        logger.info("Deduplication complete!")

        # Print summary
        print("\n=== DEDUPLICATION SUMMARY ===")
        print(f"Total unique terms: {deduplicator.report.unique_chinese_terms}")
        print(f"From glossary: {deduplicator.report.glossary_priority}")
        print(f"From candidates: {deduplicator.report.candidate_additions}")
        print(f"Duplicates found: {deduplicator.report.duplicates_found}")
        print(f"Conflicts detected: {deduplicator.report.conflicts_resolved}")
        print(f"\nOutputs:")
        print(f"  - Merged CSV: {args.output}")
        print(f"  - DuckDB: {db_path}")
        print(f"  - Report: {args.report}")

        if deduplicator.conflicts:
            print(f"\n⚠️  {len(deduplicator.conflicts)} conflicts detected. Review {args.report} for details.")

        return 0

    except Exception as e:
        logger.error(f"Deduplication failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
