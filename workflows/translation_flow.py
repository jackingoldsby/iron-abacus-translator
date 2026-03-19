#!/usr/bin/env python3
"""
Prefect-Based Translation Workflow

Wraps the existing translation pipeline as a Prefect flow with:
- DAG-based dependency resolution
- Parallel execution for body translation (fan-out)
- Real-time progress tracking
- Quality gates with footnote validation
- Checkpoint/resume capability
- Integration-ready for web UI

This replaces orchestrate_translation_pipeline.py with a production-grade workflow system.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from prefect import flow, task, get_run_logger
from prefect.task_runners import ConcurrentTaskRunner
from prefect.states import Completed, Failed
from prefect.artifacts import create_markdown_artifact

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import existing processors
from processors.translator import TranslationService
from processors.book_translator import BookTranslator
from processors.volume_manager import VolumeManager
from utils.cleanup_character_footnotes import CharacterFootnoteCleanup, CleanupConfig
from processors.structure_validator import StructureValidator
from utils.validation.footnote_integrity_validator import FootnoteIntegrityValidator

# Import orchestration components
from scripts.orchestrate_translation_pipeline import (
    OrchestrationConfig,
    PipelineStage,
    WIPManager,
    MetadataTranslationProcessor,
    TOCTranslationProcessor,
    HeadingTranslationProcessor,
    SpecialSectionsProcessor,
)

# Import workflow wrappers
from wrappers.volume_translation_wrapper import VolumeTranslationWrapper


# =============================================================================
# PREFECT TASKS
# =============================================================================

@task(name="Validate Footnote Integrity", retries=0, tags=["validation", "quality-gate"])
def validate_footnotes(
    data: Dict[str, Any],
    work_id: str,
    stage_name: str,
    halt_on_failure: bool = True
) -> Dict[str, Any]:
    """
    Quality gate: Validate footnote integrity.

    This is CRITICAL to prevent "hot garbage" output with mismatched footnotes.

    Args:
        data: Book data with footnotes
        work_id: Work identifier for logging
        stage_name: Current stage name
        halt_on_failure: If True, raise exception on validation failure

    Returns:
        Validated data (unchanged)

    Raises:
        ValueError: If validation fails and halt_on_failure=True
    """
    logger = get_run_logger()
    logger.info(f"🔍 Validating footnote integrity after {stage_name}...")

    validator = FootnoteIntegrityValidator()
    result = validator.validate_book(data)

    # Create validation artifact for UI
    artifact_md = f"""
# Footnote Validation Report - {work_id}

**Stage**: {stage_name}
**Status**: {"✓ VALID" if result.is_valid else "✗ INVALID"}

## Summary

- Blocks checked: {result.total_blocks_checked}
- Markers found: {result.total_markers_found}
- Footnotes found: {result.total_footnotes_found}

## Issues

- Missing footnotes: {result.missing_footnotes}
- Orphaned footnotes: {result.orphaned_footnotes}
- Duplicate markers: {result.duplicate_markers}
- Sequence gaps: {result.sequence_gaps}
- Marker/list mismatches: {result.marker_list_mismatches}

{"### ✓ No critical issues found!" if result.is_valid else "### ✗ Critical issues detected!"}
    """

    # Sanitize stage_name for artifact key (only lowercase, numbers, dashes)
    safe_stage_name = stage_name.lower().replace("_", "-")

    create_markdown_artifact(
        key=f"footnote-validation-{safe_stage_name}",
        markdown=artifact_md,
        description=f"Footnote validation for {work_id} after {stage_name}"
    )

    if not result.is_valid:
        error_msg = (
            f"Footnote validation FAILED after {stage_name}:\n"
            f"  - Missing footnotes: {result.missing_footnotes}\n"
            f"  - Orphaned footnotes: {result.orphaned_footnotes}\n"
            f"  - Duplicate markers: {result.duplicate_markers}\n"
            f"  - Total issues: {len(result.issues)}"
        )
        logger.error(error_msg)

        if halt_on_failure:
            raise ValueError(f"Footnote integrity check failed: {len(result.issues)} issues found")
        else:
            logger.warning("Continuing despite validation failure...")

    else:
        logger.info(f"✓ Footnote validation PASSED - {result.total_markers_found} markers validated")

    return data


@task(name="Translate Body Content", retries=2, tags=["translation", "parallel"])
def translate_body(
    data: Dict[str, Any],
    config: OrchestrationConfig,
    work_id: str,
    volume_id: Optional[str],
    wip_manager: WIPManager
) -> Dict[str, Any]:
    """
    Translate body content using VolumeTranslationWrapper (parallel processing).

    Args:
        data: Book data
        config: Translation configuration
        work_id: Work identifier
        volume_id: Optional volume identifier
        wip_manager: WIP manager for checkpoints

    Returns:
        Data with translated body content
    """
    logger = get_run_logger()
    logger.info(f"📚 Translating body content for {work_id} (parallel: {config.max_workers} workers)...")

    # Initialize VolumeTranslationWrapper
    wrapper = VolumeTranslationWrapper(
        work_id=work_id,
        max_workers=config.max_workers,
        config_name=config.volume_config_name,
        quality_threshold=config.quality_threshold,
        max_retries=config.max_retries
    )

    # Execute volume translation
    result = wrapper.execute(
        volume_data=data,
        work_id=work_id,
        volume_id=volume_id
    )

    # Log statistics
    if result.translated_volume:
        data = result.translated_volume
        stats = result.statistics

        logger.info(f"✓ Body translation complete:")
        logger.info(f"  - Body blocks: {stats.body_blocks_count} (avg quality: {stats.body_avg_quality:.1f}/10)")
        logger.info(f"  - Non-body blocks: {stats.non_body_blocks_count} (avg quality: {stats.non_body_avg_quality:.1f}/10)")
        logger.info(f"  - Overall quality: {stats.average_quality:.1f}/10")
        logger.info(f"  - Total footnotes: {stats.total_footnotes}")
        logger.info(f"  - Footnote mismatches: {stats.total_footnote_mismatches}")
        logger.info(f"  - Time: {stats.total_translation_time:.1f}s")

        # Check validation
        validation = result.validation_report
        if not validation.is_valid:
            logger.warning(f"⚠ Validation warnings (translations saved):")
            for error in validation.validation_errors[:5]:
                logger.warning(f"  - {error}")
    else:
        error_msg = f"Body translation failed: {result.error_details}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    return data


@task(name="Translate Metadata", retries=2, tags=["translation"])
def translate_metadata(
    data: Dict[str, Any],
    config: OrchestrationConfig,
    work_id: str,
    wip_manager: WIPManager
) -> Dict[str, Any]:
    """
    Translate metadata (title, author) - NO footnotes.

    Args:
        data: Book data
        config: Configuration
        work_id: Work identifier
        wip_manager: WIP manager for checkpoints

    Returns:
        Data with translated metadata
    """
    logger = get_run_logger()
    logger.info(f"📝 Translating metadata for {work_id}...")

    processor = MetadataTranslationProcessor(config, wip_manager)
    data = processor.process(data, work_id)

    logger.info("✓ Metadata translation complete")
    return data


@task(name="Translate TOC", retries=2, tags=["translation"])
def translate_toc(
    data: Dict[str, Any],
    config: OrchestrationConfig,
    work_id: str,
    wip_manager: WIPManager
) -> Dict[str, Any]:
    """
    Translate table of contents - NO footnotes.

    Args:
        data: Book data
        config: Configuration
        work_id: Work identifier
        wip_manager: WIP manager for checkpoints

    Returns:
        Data with translated TOC
    """
    logger = get_run_logger()
    logger.info(f"📑 Translating TOC for {work_id}...")

    processor = TOCTranslationProcessor(config, wip_manager)
    data = processor.process(data, work_id)

    logger.info("✓ TOC translation complete")
    return data


@task(name="Translate Headings", retries=2, tags=["translation"])
def translate_headings(
    data: Dict[str, Any],
    config: OrchestrationConfig,
    work_id: str,
    wip_manager: WIPManager
) -> Dict[str, Any]:
    """
    Translate chapter headings - NO footnotes.

    Args:
        data: Book data
        config: Configuration
        work_id: Work identifier
        wip_manager: WIP manager for checkpoints

    Returns:
        Data with translated headings
    """
    logger = get_run_logger()
    logger.info(f"📰 Translating headings for {work_id}...")

    processor = HeadingTranslationProcessor(config, wip_manager)
    data = processor.process(data, work_id)

    logger.info("✓ Heading translation complete")
    return data


@task(name="Cleanup Character Footnotes", retries=1, tags=["cleanup"])
def cleanup_character_footnotes(
    data: Dict[str, Any],
    config: OrchestrationConfig,
    work_id: str
) -> Dict[str, Any]:
    """
    Remove redundant character name footnotes.

    Args:
        data: Book data with footnotes
        config: Configuration
        work_id: Work identifier

    Returns:
        Data with cleaned footnotes
    """
    logger = get_run_logger()
    logger.info(f"🧹 Cleaning character footnotes for {work_id}...")

    if not config.enable_footnote_cleanup:
        logger.info("Footnote cleanup disabled - skipping")
        return data

    # Use CharacterFootnoteCleanup
    cleanup_config = CleanupConfig(
        model=config.model,
        temperature=0.1,
        batch_size=config.footnote_batch_size,
        preserve_historical=config.preserve_historical,
        preserve_legendary=config.preserve_legendary,
        preserve_cultural=config.preserve_cultural,
        dry_run=False
    )

    footnote_processor = CharacterFootnoteCleanup(cleanup_config)

    # Process in-memory
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)

    try:
        cleanup_result = footnote_processor.process_file(
            input_path=tmp_path,
            output_path=tmp_path,
            dry_run=False
        )

        # Load cleaned data
        with open(tmp_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        logger.info(f"✓ Removed {cleanup_result.removed_count} redundant character footnotes")
        logger.info(f"✓ Preserved {cleanup_result.preserved_count} cultural/historical footnotes")
    finally:
        tmp_path.unlink(missing_ok=True)

    return data


@task(name="Final Validation", retries=0, tags=["validation"])
def final_validation(
    data: Dict[str, Any],
    config: OrchestrationConfig,
    work_id: str
) -> Dict[str, Any]:
    """
    Final translation validation.

    Args:
        data: Completed book data
        config: Configuration
        work_id: Work identifier

    Returns:
        Validated data
    """
    logger = get_run_logger()
    logger.info(f"🔍 Running final validation for {work_id}...")

    # Use StructureValidator
    validator = StructureValidator(
        model=config.model,
        temperature=0.3
    )

    validation_result = validator.validate(data)

    logger.info(f"Structure quality: {validation_result.structure_quality:.1f}/100")
    logger.info(f"TOC coverage: {validation_result.toc_coverage:.1f}%")

    if validation_result.issues:
        logger.warning(f"Found {len(validation_result.issues)} validation issues:")
        for issue in validation_result.issues[:10]:
            logger.warning(f"  [{issue.severity}] {issue.message}")

    logger.info("✓ Final validation complete")
    return data


# =============================================================================
# MAIN WORKFLOW
# =============================================================================

@flow(
    name="Translation Pipeline",
    description="Complete book translation workflow with quality gates",
    task_runner=ConcurrentTaskRunner(),
    log_prints=True
)
def translation_workflow(
    work_id: str,
    volume: Optional[str] = None,
    config: Optional[OrchestrationConfig] = None,
    resume: bool = False,
    workflow_id: str = "unknown",
    workflow_name: str = "Unknown Workflow"
) -> Dict[str, Any]:
    """
    Complete translation workflow with DAG-based execution.

    This flow:
    1. Translates metadata (sequential)
    2. Translates TOC (sequential, depends on metadata)
    3. Translates headings (sequential, depends on TOC)
    4. Translates body chapters (PARALLEL with fan-out)
    5. Validates footnotes (quality gate - HALT on failure)
    6. Cleans character footnotes
    7. Re-validates footnotes (quality gate)
    8. Final validation

    Args:
        work_id: Work identifier (e.g., "D1379")
        volume: Optional volume identifier
        config: Orchestration configuration
        resume: Resume from checkpoint

    Returns:
        Final translated data
    """
    logger = get_run_logger()

    if config is None:
        config = OrchestrationConfig()

    wip_manager = WIPManager(config)

    logger.info(f"{'='*60}")
    logger.info(f"Starting Translation Workflow: {work_id}")
    if volume:
        logger.info(f"Volume: {volume}")
    logger.info(f"{'='*60}")

    # Load source data from cleaned files
    logger.info(f"\n📂 Loading source data...")
    volume_manager = VolumeManager(
        catalog_path=config.catalog_path,
        source_dir=config.source_dir,
        output_dir=config.output_dir
    )

    volumes = volume_manager.get_volumes_for_work(work_id)
    if not volumes:
        raise ValueError(f"No volumes found for work {work_id}")

    # Filter to specific volume if requested
    if volume:
        volumes = [v for v in volumes if v.volume == volume]
        if not volumes:
            raise ValueError(f"Volume {volume} not found for work {work_id}")

    vol_info = volumes[0]  # Process first volume
    if not vol_info.cleaned_json_path or not vol_info.cleaned_json_path.exists():
        raise FileNotFoundError(f"Cleaned JSON not found: {vol_info.cleaned_json_path}")

    # Load the cleaned JSON
    with open(vol_info.cleaned_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    logger.info(f"✓ Loaded: {vol_info.cleaned_json_path.name}")

    # Stage 1: Metadata Translation
    logger.info("\n🏁 Stage 1: Metadata Translation")
    data = translate_metadata(data, config, work_id, wip_manager)

    # Stage 2: TOC Translation
    logger.info("\n🏁 Stage 2: TOC Translation")
    data = translate_toc(data, config, work_id, wip_manager)

    # Stage 3: Headings Translation
    logger.info("\n🏁 Stage 3: Headings Translation")
    data = translate_headings(data, config, work_id, wip_manager)

    # Stage 4: Body Translation (PARALLEL via VolumeTranslationWrapper)
    logger.info("\n🏁 Stage 4: Body Translation (Parallel)")
    data = translate_body(data, config, work_id, vol_info.volume, wip_manager)
    wip_manager.save_wip(data, work_id, PipelineStage.BODY)

    # QUALITY GATE: Validate footnotes after body translation
    logger.info("\n🚦 Quality Gate: Footnote Validation (after body)")
    data = validate_footnotes(data, work_id, "body_translation", halt_on_failure=True)

    # Stage 5: Special Sections (placeholder for now)
    logger.info("\n🏁 Stage 5: Special Sections")
    # TODO: Implement special sections translation
    wip_manager.save_wip(data, work_id, PipelineStage.SPECIAL)

    # Stage 6: Footnote Cleanup
    logger.info("\n🏁 Stage 6: Footnote Cleanup")
    data = cleanup_character_footnotes(data, config, work_id)
    wip_manager.save_wip(data, work_id, PipelineStage.CLEANUP)

    # QUALITY GATE: Re-validate after cleanup
    logger.info("\n🚦 Quality Gate: Footnote Validation (after cleanup)")
    data = validate_footnotes(data, work_id, "footnote_cleanup", halt_on_failure=True)

    # Stage 7: Final Validation
    logger.info("\n🏁 Stage 7: Final Validation")
    data = final_validation(data, config, work_id)
    wip_manager.save_wip(data, work_id, PipelineStage.VALIDATION)

    # Save final output
    output_filename = f"translated_{work_id}_{vol_info.title}.json"
    output_path = config.output_dir / output_filename

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"\n{'='*60}")
    logger.info(f"✓ Translation Workflow Complete: {work_id}")
    logger.info(f"✓ Output saved: {output_path}")
    logger.info(f"{'='*60}\n")

    return data


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Prefect-based translation workflow'
    )
    parser.add_argument('work_id', help='Work identifier (e.g., D1379)')
    parser.add_argument('--volume', help='Volume identifier')
    parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    parser.add_argument('--workers', type=int, default=3, help='Concurrent workers')

    args = parser.parse_args()

    # Create config
    config = OrchestrationConfig()
    config.max_workers = args.workers  # For VolumeTranslationWrapper

    # Run flow
    result = translation_workflow(
        work_id=args.work_id,
        volume=args.volume,
        config=config,
        resume=args.resume
    )

    print(f"\n✓ Workflow completed successfully!")
    print(f"Result saved to: {config.output_dir}")
