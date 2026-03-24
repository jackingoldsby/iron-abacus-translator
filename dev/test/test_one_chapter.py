#!/usr/bin/env python3
"""
Test Script: Translate One Chapter with Multithreading

Quick test script to translate a single chapter using improved prompts and gpt-4.1-nano.
Useful for testing translation quality improvements before processing entire books.

Usage:
    python scripts/test_one_chapter.py D58 --chapter 1 --max-workers 8
    python scripts/test_one_chapter.py D58 --chapter 1 --max-workers 4 --model gpt-4.1-nano
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"))

from processors.book_translator import BookTranslator
from processors.translation_config import TranslationConfig, setup_logging
from utils.load_env_creds import load_env_credentials

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='Test translation on a single chapter',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Translate chapter 1 of D58 with 8 workers
  python scripts/test_one_chapter.py D58 --chapter 1 --max-workers 8

  # Use gpt-4.1-nano (default)
  python scripts/test_one_chapter.py D58 --chapter 1

  # Use specific model
  python scripts/test_one_chapter.py D58 --chapter 1 --model gpt-4.1-nano

  # Specify work number and volume
  python scripts/test_one_chapter.py D58 --volume 001 --chapter 1
        """
    )

    parser.add_argument(
        'work_number',
        help='Work number (e.g., D58, D70, I0929)'
    )

    parser.add_argument(
        '--volume',
        default='001',
        help='Volume number (default: 001)'
    )

    parser.add_argument(
        '--chapter',
        type=int,
        default=1,
        help='Chapter number to translate (default: 1)'
    )

    parser.add_argument(
        '--max-workers',
        type=int,
        default=8,
        help='Max concurrent block processing (default: 8)'
    )

    parser.add_argument(
        '--model',
        default='gpt-4.1-nano',
        help='OpenAI model to use (default: gpt-4.1-nano)'
    )

    parser.add_argument(
        '--output-dir',
        type=Path,
        default=None,  # Uses environment default (translated/)
        help='Output directory for test translation (default: from environment config)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Load API credentials
    try:
        load_env_credentials(required_keys=['OPENAI_API_KEY'])
    except Exception as e:
        logger.error(f"Failed to load API credentials: {e}")
        return 1

    # Initialize configuration
    config = TranslationConfig(
        model=args.model,
        max_concurrent_chapters=args.max_workers,
        verbose=args.verbose,
        catalog_path=None,  # Loaded from environment config
        source_dir=None,  # Loaded from environment config
        output_dir=args.output_dir
    )

    # Find source file
    from processors.volume_manager import VolumeManager

    volume_manager = VolumeManager(
        catalog_path=config.catalog_path,
        source_dir=config.source_dir,
        output_dir=config.output_dir
    )

    volumes = volume_manager.get_volumes_for_work(args.work_number)

    if not volumes:
        logger.error(f"No volumes found for work {args.work_number}")
        return 1

    # Filter to requested volume
    volumes = [v for v in volumes if v.volume == args.volume]

    if not volumes:
        logger.error(f"Volume {args.volume} not found for work {args.work_number}")
        return 1

    volume_info = volumes[0]

    # Build "Author - English Title_chN.json" output filename using epub_builder naming
    if volume_info.translated_json_path:
        try:
            from processors.epub_builder import EpubBuilder
            eb = EpubBuilder(catalog_db=config.catalog_path)
            # Load book meta to resolve English names
            with open(volume_info.cleaned_json_path, 'r', encoding='utf-8') as f:
                _meta = json.load(f).get('meta', {})
            epub_path = eb._english_epub_path(
                {'meta': _meta}, volume_info.translated_json_path.parent
            )
            # Swap .epub → _chN.json
            stem = epub_path.stem
            volume_info.translated_json_path = epub_path.with_name(f"{stem}_ch{args.chapter}.json")
        except Exception as e:
            logger.warning(f"Could not resolve English filename: {e}")
            stem = volume_info.translated_json_path.stem
            volume_info.translated_json_path = (
                volume_info.translated_json_path.parent / f"{stem}_ch{args.chapter}.json"
            )

    if not volume_info.cleaned_json_path or not volume_info.cleaned_json_path.exists():
        logger.error(f"Source file not found: {volume_info.cleaned_json_path}")
        return 1

    # Load book data
    with open(volume_info.cleaned_json_path, 'r', encoding='utf-8') as f:
        book_data = json.load(f)

    # Get requested chapter
    chapters = book_data['structure']['body']['chapters']

    if args.chapter < 1 or args.chapter > len(chapters):
        logger.error(f"Chapter {args.chapter} out of range (1-{len(chapters)})")
        return 1

    chapter = chapters[args.chapter - 1]
    chapter_id = chapter.get('id', f'chapter_{args.chapter:04d}')
    chapter_title = chapter.get('title', 'Untitled')

    print(f"\n{'='*60}")
    print(f"TEST TRANSLATION: ONE CHAPTER")
    print(f"{'='*60}\n")
    print(f"Work: {volume_info.title} by {volume_info.author}")
    print(f"Volume: {args.volume}")
    print(f"Chapter: {args.chapter} - {chapter_title}")
    print(f"Model: {config.model}")
    print(f"Workers: {config.max_concurrent_chapters}")
    print(f"\nSource: {volume_info.cleaned_json_path}")
    print(f"Output: {volume_info.translated_json_path}")
    print()

    # Initialize translator
    translator = BookTranslator(config)

    # Setup logging for this work
    work_logger = setup_logging(config, args.work_number)

    # Translate just this chapter
    start_time = datetime.now()

    work_logger.info(f"Translating chapter {args.chapter}/{len(chapters)}: {chapter_title}")

    try:
        # Create minimal book structure with just this chapter
        test_book_data = {
            'meta': book_data['meta'],
            'structure': {
                'front_matter': book_data['structure']['front_matter'],
                'body': {
                    'chapters': [chapter]  # Just one chapter
                },
                'back_matter': book_data['structure'].get('back_matter', {})
            }
        }

        # Save temporary test file
        temp_input = volume_info.cleaned_json_path.parent / f"temp_test_chapter_{args.chapter}.json"
        with open(temp_input, 'w', encoding='utf-8') as f:
            json.dump(test_book_data, f, ensure_ascii=False, indent=2)

        # Translate
        try:
            report = translator.translate_book(
                input_path=temp_input,
                output_path=volume_info.translated_json_path,
                work_number=args.work_number,
                volume=args.volume
            )
        finally:
            # Clean up temp file
            if temp_input.exists():
                temp_input.unlink()

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Print results
        print(f"\n{'='*60}")
        print("TRANSLATION COMPLETE")
        print(f"{'='*60}\n")

        if report.get('success', True):
            stats = report.get('statistics', {})
            print(f"✓ Chapter: {chapter_title}")
            print(f"✓ Blocks: {stats.get('successful_blocks')}/{stats.get('total_blocks')}")
            print(f"✓ Success Rate: {stats.get('success_rate', 0):.1f}%")
            print(f"✓ Tokens: {stats.get('total_tokens', 0):,}")
            print(f"✓ Estimated Cost: ${stats.get('estimated_cost_usd', 0):.4f}")
            print(f"✓ Duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")

            if report.get('errors'):
                print(f"\n⚠ Errors: {len(report['errors'])}")
                for error in report['errors'][:5]:
                    print(f"  - {error}")

            print(f"\n📄 Output: {volume_info.translated_json_path}")

            # Show sample translation
            print(f"\n{'='*60}")
            print("SAMPLE TRANSLATION (first 3 blocks)")
            print(f"{'='*60}\n")

            with open(volume_info.translated_json_path, 'r', encoding='utf-8') as f:
                result = json.load(f)

            translated_chapter = result['structure']['body']['chapters'][0]
            for i, block in enumerate(translated_chapter['content_blocks'][:3]):
                if block.get('translated_content'):
                    print(f"Block {i+1}:")
                    print(f"  Original: {block['original_content'][:80]}...")
                    print(f"  Translation: {block['translated_content'][:150]}...")
                    print()

            return 0
        else:
            print(f"✗ Translation failed: {report.get('error')}")
            return 1

    except Exception as e:
        logger.error(f"Translation failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
