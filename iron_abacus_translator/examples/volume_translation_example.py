#!/usr/bin/env python3
"""
Volume Translation Example

Demonstrates how to use VolumeTranslationWrapper for parallel volume translation
with comprehensive statistics and validation.

Usage:
    python examples/volume_translation_example.py

Requirements:
    - OPENAI_API_KEY environment variable set
    - Cleaned volume JSON file
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from wrappers import VolumeTranslationWrapper


# =============================================================================
# CONFIGURATION
# =============================================================================

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


# =============================================================================
# EXAMPLE 1: BASIC USAGE
# =============================================================================

def example_basic_translation():
    """Basic volume translation with default settings"""
    print("\n" + "=" * 80)
    print("EXAMPLE 1: Basic Volume Translation")
    print("=" * 80 + "\n")

    # Sample volume data (replace with your actual data)
    volume_data = {
        "structure": {
            "metadata": {
                "title": "測試小說",
                "author": "測試作者",
                "content": "測試元數據"
            },
            "body": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "第一章",
                        "content_blocks": [
                            {
                                "id": "block_0001",
                                "content": "且言紂王只因進香之後，看見女媧美貌，朝暮思想，寒暑盡忘。"
                            }
                        ]
                    }
                ]
            }
        }
    }

    # Initialize wrapper
    wrapper = VolumeTranslationWrapper()

    # Execute translation
    result = wrapper.execute(
        volume_data=volume_data,
        work_id="EXAMPLE"
    )

    # Print results
    print(f"\nTranslation Result:")
    print(f"  Success: {result.success}")
    print(f"  Total blocks: {result.statistics.total_blocks}")
    print(f"  Successful: {result.statistics.successful_blocks}")
    print(f"  Failed: {result.statistics.failed_blocks}")
    print(f"  Average quality: {result.statistics.average_quality:.1f}/10")

    if result.success:
        print(f"\n✓ Translation completed successfully!")
    else:
        print(f"\n✗ Translation failed:")
        if result.validation_report:
            for error in result.validation_report.validation_errors:
                print(f"  - {error}")


# =============================================================================
# EXAMPLE 2: STATISTICS ANALYSIS
# =============================================================================

def example_statistics_analysis():
    """Detailed statistics analysis from translation result"""
    print("\n" + "=" * 80)
    print("EXAMPLE 2: Statistics Analysis")
    print("=" * 80 + "\n")

    # Sample volume (multi-chapter)
    volume_data = {
        "structure": {
            "body": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "content_blocks": [
                            {"id": "block_0001", "content": "章節一內容一。" * 10},
                            {"id": "block_0002", "content": "章節一內容二。" * 10}
                        ]
                    },
                    {
                        "chapter_number": 2,
                        "content_blocks": [
                            {"id": "block_0003", "content": "章節二內容一。" * 10}
                        ]
                    }
                ]
            },
            "front_matter": {
                "introduction": {
                    "content": "前言內容。" * 5
                }
            }
        }
    }

    wrapper = VolumeTranslationWrapper()
    result = wrapper.execute(volume_data, work_id="STATS_EXAMPLE")

    # Print detailed statistics
    stats = result.statistics

    print("\nBlock Counts:")
    print(f"  Total: {stats.total_blocks}")
    print(f"  Body: {stats.body_blocks_count}")
    print(f"  Non-Body: {stats.non_body_blocks_count}")

    print("\nSuccess Metrics:")
    print(f"  Successful: {stats.successful_blocks}")
    print(f"  Failed: {stats.failed_blocks}")
    print(f"  Success Rate: {stats.success_rate * 100:.1f}%")

    print("\nQuality Metrics:")
    print(f"  Overall Average: {stats.average_quality:.2f}")
    print(f"  Body Average: {stats.body_avg_quality:.2f}")
    print(f"  Non-Body Average: {stats.non_body_avg_quality:.2f}")
    print(f"  Min Quality: {stats.min_quality:.2f}")
    print(f"  Max Quality: {stats.max_quality:.2f}")

    print("\nFootnote Metrics:")
    print(f"  Total: {stats.total_footnotes}")
    print(f"  Body: {stats.body_footnotes}")
    print(f"  Non-Body: {stats.non_body_footnotes}")
    print(f"  Mismatches: {stats.total_footnote_mismatches}")

    print("\nPerformance Metrics:")
    print(f"  Total Time: {stats.total_translation_time:.1f}s")
    print(f"  Avg Time/Block: {stats.avg_time_per_block:.1f}s")

    print("\nCharacter Counts:")
    print(f"  Source: {stats.total_source_chars:,}")
    print(f"  Translated: {stats.total_translated_chars:,}")
    print(f"  Length Ratio: {stats.avg_length_ratio:.2f}")


# =============================================================================
# EXAMPLE 3: CONFIGURATION OPTIONS
# =============================================================================

def example_configuration_options():
    """Different configuration modes"""
    print("\n" + "=" * 80)
    print("EXAMPLE 3: Configuration Options")
    print("=" * 80 + "\n")

    sample_volume = {
        "structure": {
            "body": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "content_blocks": [
                            {"id": "block_0001", "content": "測試內容。" * 10}
                        ]
                    }
                ]
            }
        }
    }

    # Option 1: Default mode
    print("\n--- Default Mode ---")
    wrapper_default = VolumeTranslationWrapper()
    print(f"Max workers: {wrapper_default.max_workers}")
    print(f"Quality threshold: {wrapper_default.aggregate_quality_threshold}")

    # Option 2: Strict mode (requires config file)
    # print("\n--- Strict Mode ---")
    # wrapper_strict = VolumeTranslationWrapper(config_name="strict")
    # print(f"Max workers: {wrapper_strict.max_workers}")
    # print(f"Quality threshold: {wrapper_strict.aggregate_quality_threshold}")

    # Option 3: Fast mode (requires config file)
    # print("\n--- Fast Mode ---")
    # wrapper_fast = VolumeTranslationWrapper(config_name="fast")
    # print(f"Max workers: {wrapper_fast.max_workers}")
    # print(f"Quality threshold: {wrapper_fast.aggregate_quality_threshold}")

    # Option 4: Custom overrides
    print("\n--- Custom Overrides ---")
    wrapper_custom = VolumeTranslationWrapper(
        max_workers=10,
        aggregate_quality_threshold=8.5
    )
    print(f"Max workers: {wrapper_custom.max_workers}")
    print(f"Quality threshold: {wrapper_custom.aggregate_quality_threshold}")


# =============================================================================
# EXAMPLE 4: ERROR HANDLING
# =============================================================================

def example_error_handling():
    """Handling failures and validation errors"""
    print("\n" + "=" * 80)
    print("EXAMPLE 4: Error Handling")
    print("=" * 80 + "\n")

    # Volume with some problematic content
    volume_data = {
        "structure": {
            "body": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "content_blocks": [
                            {"id": "block_0001", "content": "正常內容。" * 10},
                            {"id": "block_0002", "content": ""},  # Empty content
                        ]
                    }
                ]
            }
        }
    }

    wrapper = VolumeTranslationWrapper()
    result = wrapper.execute(volume_data, work_id="ERROR_EXAMPLE")

    # Check for failures
    if not result.success:
        print("\nTranslation failed. Analyzing errors...\n")

        # Check validation report
        if result.validation_report:
            report = result.validation_report

            print("Validation Report:")
            print(f"  Quality passed: {report.quality_passed}")
            print(f"  Footnote passed: {report.footnote_validation_passed}")

            if report.validation_errors:
                print("\nErrors:")
                for error in report.validation_errors:
                    print(f"  - {error}")

            if report.failed_blocks:
                print(f"\nFailed blocks: {len(report.failed_blocks)}")
                for block_id in report.failed_blocks:
                    print(f"  - {block_id}")

        # Check individual block results
        print(f"\nBlock Results:")
        for block_result in result.block_results:
            status = "✓" if block_result.success else "✗"
            print(f"  {status} {block_result.block_id}")
            if not block_result.success and block_result.error_message:
                print(f"      Error: {block_result.error_message}")


# =============================================================================
# EXAMPLE 5: SAVE AND LOAD
# =============================================================================

def example_save_and_load():
    """Save translated volume and manifest"""
    print("\n" + "=" * 80)
    print("EXAMPLE 5: Save and Load")
    print("=" * 80 + "\n")

    volume_data = {
        "structure": {
            "body": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "content_blocks": [
                            {"id": "block_0001", "content": "測試內容。" * 10}
                        ]
                    }
                ]
            }
        }
    }

    wrapper = VolumeTranslationWrapper()
    result = wrapper.execute(volume_data, work_id="SAVE_EXAMPLE")

    if result.success:
        # Save translated volume
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        volume_path = output_dir / "translated_volume.json"
        with open(volume_path, "w", encoding="utf-8") as f:
            json.dump(result.translated_volume, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Saved translated volume to: {volume_path}")

        # Save manifest
        manifest_path = output_dir / "translation_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(result.manifest, f, indent=2, ensure_ascii=False)
        print(f"✓ Saved manifest to: {manifest_path}")

        # Save statistics
        stats_path = output_dir / "translation_statistics.json"
        stats_dict = {
            "total_blocks": result.statistics.total_blocks,
            "successful_blocks": result.statistics.successful_blocks,
            "failed_blocks": result.statistics.failed_blocks,
            "average_quality": result.statistics.average_quality,
            "total_footnotes": result.statistics.total_footnotes,
            "total_translation_time": result.statistics.total_translation_time
        }
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats_dict, f, indent=2)
        print(f"✓ Saved statistics to: {stats_path}")


# =============================================================================
# EXAMPLE 6: VISUAL PROGRESS
# =============================================================================

def example_visual_progress():
    """Translation with visual progress bar"""
    print("\n" + "=" * 80)
    print("EXAMPLE 6: Visual Progress")
    print("=" * 80 + "\n")

    # Larger volume for progress bar demo
    volume_data = {
        "structure": {
            "body": {
                "chapters": [
                    {
                        "chapter_number": i,
                        "content_blocks": [
                            {
                                "id": f"block_{i:04d}",
                                "content": f"章節{i}的內容。" * 10
                            }
                        ]
                    }
                    for i in range(1, 6)  # 5 chapters
                ]
            }
        }
    }

    print("Starting translation with progress bar...\n")

    wrapper = VolumeTranslationWrapper(max_workers=3)
    result = wrapper.execute(volume_data, work_id="PROGRESS_EXAMPLE")

    print("\n\nTranslation completed!")
    print(f"Time: {result.statistics.total_translation_time:.1f}s")
    print(f"Avg quality: {result.statistics.average_quality:.1f}/10")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run all examples"""
    print("\n" + "=" * 80)
    print("VOLUME TRANSLATION WRAPPER - EXAMPLES")
    print("=" * 80)

    # Check API key
    if not os.getenv("OPENAI_API_KEY"):
        print("\nWarning: OPENAI_API_KEY not set. Examples may fail.")
        print("Set it with: export OPENAI_API_KEY=your-key-here\n")
        return 1

    try:
        # Run examples
        example_basic_translation()
        # example_statistics_analysis()  # Uncomment to run
        # example_configuration_options()  # Uncomment to run
        # example_error_handling()  # Uncomment to run
        # example_save_and_load()  # Uncomment to run
        # example_visual_progress()  # Uncomment to run

        print("\n" + "=" * 80)
        print("Examples completed!")
        print("=" * 80 + "\n")

        return 0

    except Exception as e:
        logger.error(f"Example failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
