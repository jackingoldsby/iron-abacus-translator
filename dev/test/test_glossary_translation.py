#!/usr/bin/env python3
"""
Test Glossary-Integrated Translation

Tests the wuxia glossary integration on wuxia_0004.
Demonstrates:
- Glossary term matching
- Exact translation forms and footnotes from glossary
- Combined glossary + custom footnotes
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"))

from processors.book_translator import BookTranslator
from processors.translation_config import TranslationConfig
from utils.load_env_creds import load_env_credentials

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Test translation with glossary integration"""

    # Load API credentials
    try:
        load_env_credentials(required_keys=['OPENAI_API_KEY'])
    except Exception as e:
        logger.error(f"Failed to load API credentials: {e}")
        return 1

    # Input/Output paths
    from utils.environment_config import get_or_create_config
    _env = get_or_create_config()
    input_path = _env.source_dir / "wuxia_0124" / "cleaned_I1046_飛鳳潛龍_梁羽生.json"
    output_dir = _env.output_dir / "test_translations" / "wuxia_0124"
    output_path = output_dir / "translated_I1046_飛鳳潛龍_梁羽生.json"

    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        logger.error("\nLooking for alternatives in source dir...")
        alternatives = list(_env.source_dir.rglob("cleaned_I09B3_*.json"))[:2]
        for alt in alternatives:
            logger.info(f"  Found: {alt}")
        return 1

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize configuration
    config = TranslationConfig(
        model='gpt-4.1-nano',  # Use gpt-4.1-nano for testing
        temperature=0.3,
        max_retries=2,
        timeout=120,
        dry_run=False,
        save_checkpoints=True,
        skip_completed=False,
        verbose=True
    )

    # Initialize translator
    logger.info("Initializing translator with glossary integration...")
    translator = BookTranslator(config)

    # Print glossary info
    if translator.translation_service.glossary:
        logger.info("✓ Wuxia glossary loaded successfully")

        # Test a few lookups
        test_terms = ["內功", "輕功", "武林", "少林"]
        logger.info("\nSample glossary entries:")
        for term in test_terms:
            entry = translator.translation_service.glossary.lookup(term)
            if entry:
                logger.info(f"  {term}:")
                logger.info(f"    Pinyin: {entry.pinyin}")
                logger.info(f"    Strategy: {entry.translation_strategy}")
                logger.info(f"    Form: {entry.recommended_form}")
                logger.info(f"    Dedup: {entry.deduplication_strategy}")
    else:
        logger.warning("⚠ Glossary not loaded")

    # Translate book
    print(f"\n{'='*60}")
    print("TRANSLATION TEST: wuxia_0124 (飛鳳潛龍 by 梁羽生)")
    print(f"{'='*60}\n")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}\n")

    start_time = datetime.now()

    report = translator.translate_book(
        input_path=input_path,
        output_path=output_path,
        work_number="I1046",
        volume=None
    )

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Print report
    print(f"\n{'='*60}")
    print("TRANSLATION REPORT")
    print(f"{'='*60}\n")

    if report.get('success', True):
        print(f"✓ Translation completed successfully")
        print(f"  Duration: {duration/60:.1f} minutes")
        print(f"  Chapters: {report['total_chapters']}")
        print(f"  Blocks: {report['successful_blocks']}/{report['total_blocks']}")
        print(f"  Success Rate: {(report['successful_blocks']/report['total_blocks']*100):.1f}%")
        print(f"  Tokens: {report['total_tokens']:,}")
        print(f"  Estimated Cost: ${report['total_tokens'] * 0.00015 / 1000:.4f}")

        if report.get('errors'):
            print(f"\n⚠ Errors: {len(report['errors'])}")
            for error in report['errors'][:5]:
                print(f"  - {error}")

        if report.get('warnings'):
            print(f"\n⚠ Warnings: {len(report['warnings'])}")
            for warning in report['warnings'][:5]:
                print(f"  - {warning}")

        # Analyze sample translated blocks
        print(f"\n{'='*60}")
        print("SAMPLE TRANSLATIONS (showing glossary integration)")
        print(f"{'='*60}\n")

        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                translated_data = json.load(f)

            # Find first chapter with glossary terms
            chapters = translated_data['structure']['body']['chapters']
            for chapter in chapters[:3]:  # Check first 3 chapters
                for block in chapter['content_blocks'][:5]:  # Check first 5 blocks per chapter
                    if 'footnotes' in block and block['footnotes']:
                        print(f"Chapter: {chapter.get('title', 'Untitled')}")
                        print(f"Block ID: {block['id']}")
                        print(f"\nOriginal Chinese:")
                        print(f"  {block.get('original_content', 'N/A')[:200]}...")
                        print(f"\nTranslated English:")
                        print(f"  {block.get('translated_content', 'N/A')[:200]}...")
                        print(f"\nFootnotes ({len(block['footnotes'])} total):")
                        for fn in block['footnotes'][:3]:
                            print(f"  [{fn['key']}] {fn['ideogram']} ({fn['pinyin']})")
                            print(f"      {fn['explanation'][:150]}...")
                        print()

                        # Only show 2 examples
                        if chapters.index(chapter) >= 1:
                            break
                else:
                    continue
                break

        except Exception as e:
            logger.error(f"Failed to analyze translations: {e}")

        # Save detailed report
        report_path = output_dir / "translation_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n📄 Full report saved: {report_path}")

        return 0

    else:
        print(f"✗ Translation failed: {report.get('error')}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
