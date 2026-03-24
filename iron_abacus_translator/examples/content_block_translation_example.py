#!/usr/bin/env python3
"""
Example: Content Block Translation Wrapper

Demonstrates how to use the ContentBlockTranslationWrapper for translating
individual content blocks with footnote validation and quality checks.
"""

import sys
import json
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper


def setup_logging():
    """Configure logging"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def example_1_basic_translation():
    """Example 1: Basic translation with default settings"""
    print("\n" + "=" * 80)
    print("EXAMPLE 1: Basic Translation")
    print("=" * 80)

    wrapper = ContentBlockTranslationWrapper(
        max_retries=5,
        quality_threshold=9.5
    )

    result = wrapper.execute(
        content_text_id=1,
        content_source_text="且言紂王只因進香之後，看見女媧美貌，朝暮思想，寒暑盡忘。",
        work_id="EXAMPLE"
    )

    if result.success:
        print(f"✓ Translation successful!")
        print(f"  Quality Score: {result.validation_report.quality_score:.1f}/10")
        print(f"  Footnotes: {result.validation_report.footnote_marker_count}")
        print(f"  Attempts: {result.attempts_used}")
        print(f"\nTranslated Text:")
        print(f"  {result.translated_data['translated_annotated_content']['annotated_content_text'][:200]}...")
    else:
        print(f"✗ Translation failed")
        print(f"  Error: {result.error_details}")
        print(f"  Attempts: {result.attempts_used}")


def example_2_custom_configuration():
    """Example 2: Custom configuration with lower threshold"""
    print("\n" + "=" * 80)
    print("EXAMPLE 2: Custom Configuration")
    print("=" * 80)

    wrapper = ContentBlockTranslationWrapper(
        model="gpt-4.1-nano",
        temperature=0.5,
        max_retries=3,
        quality_threshold=8.0,  # Lower threshold
        timeout=60
    )

    result = wrapper.execute(
        content_text_id=2,
        content_source_text="魯世雄道：「師父，你老人家這一手也忒厲害了。」",
        work_id="EXAMPLE"
    )

    print(f"Configuration:")
    print(f"  Model: {wrapper.model}")
    print(f"  Temperature: {wrapper.temperature}")
    print(f"  Quality Threshold: {wrapper.quality_threshold}")
    print(f"  Max Retries: {wrapper.max_retries}")

    if result.success:
        print(f"\n✓ Translation successful!")
        print(f"  Quality: {result.validation_report.quality_score:.1f}/10")
        print(f"  Attempts: {result.attempts_used}")
    else:
        print(f"\n✗ Translation failed: {result.error_details}")


def example_3_batch_translation():
    """Example 3: Translate multiple blocks"""
    print("\n" + "=" * 80)
    print("EXAMPLE 3: Batch Translation")
    print("=" * 80)

    wrapper = ContentBlockTranslationWrapper()

    blocks = [
        {
            "id": 1,
            "content": "且言紂王只因進香之後，看見女媧美貌。"
        },
        {
            "id": 2,
            "content": "魯世雄道：「師父，你老人家這一手也忒厲害了。」"
        },
        {
            "id": 3,
            "content": "這時候，天色已經黑了下來。"
        }
    ]

    results = []
    for block in blocks:
        print(f"\nTranslating block {block['id']}...")

        result = wrapper.execute(
            content_text_id=block["id"],
            content_source_text=block["content"],
            work_id="BATCH_EXAMPLE"
        )

        results.append({
            "block_id": block["id"],
            "success": result.success,
            "quality": result.validation_report.quality_score if result.success else None,
            "attempts": result.attempts_used
        })

        if result.success:
            print(f"  ✓ Success (quality: {result.validation_report.quality_score:.1f}/10, attempts: {result.attempts_used})")
        else:
            print(f"  ✗ Failed (attempts: {result.attempts_used})")

    # Summary
    print(f"\n{'='*80}")
    print("BATCH SUMMARY")
    print(f"{'='*80}")
    print(f"Total blocks: {len(blocks)}")
    print(f"Successful: {sum(1 for r in results if r['success'])}")
    print(f"Failed: {sum(1 for r in results if not r['success'])}")
    print(f"Average attempts: {sum(r['attempts'] for r in results) / len(results):.1f}")


def example_4_error_handling():
    """Example 4: Error handling with invalid input"""
    print("\n" + "=" * 80)
    print("EXAMPLE 4: Error Handling")
    print("=" * 80)

    wrapper = ContentBlockTranslationWrapper()

    # Test invalid input
    print("\nTest 1: Empty source text")
    result = wrapper.execute(
        content_text_id=1,
        content_source_text="",
        work_id="ERROR_TEST"
    )

    if not result.success:
        print(f"  ✓ Correctly rejected: {result.error_details['validation_errors']}")

    # Test too short text
    print("\nTest 2: Too short source text")
    result = wrapper.execute(
        content_text_id=2,
        content_source_text="Hi",
        work_id="ERROR_TEST"
    )

    if not result.success:
        print(f"  ✓ Correctly rejected: {result.error_details['validation_errors']}")

    # Test None content_text_id
    print("\nTest 3: None content_text_id")
    result = wrapper.execute(
        content_text_id=None,
        content_source_text="Some valid text here",
        work_id="ERROR_TEST"
    )

    if not result.success:
        print(f"  ✓ Correctly rejected: {result.error_details['validation_errors']}")


def example_5_manifest_inspection():
    """Example 5: Inspect manifest and metrics"""
    print("\n" + "=" * 80)
    print("EXAMPLE 5: Manifest Inspection")
    print("=" * 80)

    wrapper = ContentBlockTranslationWrapper()

    result = wrapper.execute(
        content_text_id=1,
        content_source_text="且言紂王只因進香之後，看見女媧美貌，朝暮思想，寒暑盡忘。",
        work_id="MANIFEST_EXAMPLE"
    )

    if result.success:
        print("\nManifest:")
        print(json.dumps(result.manifest, indent=2))

        print("\nMetrics:")
        print(json.dumps(result.metrics, indent=2))

        print("\nValidation Report:")
        print(f"  Valid: {result.validation_report.is_valid}")
        print(f"  Quality Score: {result.validation_report.quality_score:.1f}/10")
        print(f"  Footnote Markers: {result.validation_report.footnote_marker_count}")
        print(f"  Footnote Array: {result.validation_report.footnote_array_count}")
        print(f"  Errors: {result.validation_report.errors}")
        print(f"  Warnings: {result.validation_report.warnings}")
    else:
        print(f"Translation failed: {result.error_details}")


def main():
    """Run all examples"""
    setup_logging()

    print("\n" + "=" * 80)
    print("CONTENT BLOCK TRANSLATION WRAPPER - EXAMPLES")
    print("=" * 80)

    try:
        # Run examples
        example_1_basic_translation()
        example_2_custom_configuration()
        example_3_batch_translation()
        example_4_error_handling()
        example_5_manifest_inspection()

        print("\n" + "=" * 80)
        print("ALL EXAMPLES COMPLETED")
        print("=" * 80)

        return 0

    except Exception as e:
        print(f"\nError running examples: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
