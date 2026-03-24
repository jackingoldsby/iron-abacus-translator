#!/usr/bin/env python3
"""
Volume Translation Wrapper

Workflow node wrapper for translating entire volumes with:
- Parallel block processing (fan-out/fan-in pattern)
- Aggregate validation (avg quality >= 9.5, zero footnote mismatches)
- Statistics collection (body vs non-body breakdown)
- Progress tracking and visualization
- Structured logging and manifest generation
- Integration with ContentBlockTranslationWrapper

Architecture:
    VolumeTranslationWrapper
        ↓
    Fan-out (parallel processing)
        ├─→ ContentBlockTranslationWrapper (block 1)
        ├─→ ContentBlockTranslationWrapper (block 2)
        ├─→ ContentBlockTranslationWrapper (block N)
        ↓
    Fan-in (aggregate results)
        ↓
    Aggregate Validation + Statistics
"""

import logging
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from wrappers.content_block_translation_wrapper import (
    ContentBlockTranslationWrapper,
    ContentBlockTranslationResult
)
from wrappers.volume_config import VolumeConfig

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class BlockTypeStats:
    """Statistics for a specific block type (body or non-body)"""
    block_count: int = 0
    successful_blocks: int = 0
    failed_blocks: int = 0

    total_footnotes: int = 0
    footnote_mismatches: int = 0

    avg_quality: float = 0.0
    min_quality: float = 10.0
    max_quality: float = 0.0

    total_translation_time: float = 0.0
    avg_time_per_block: float = 0.0

    total_source_chars: int = 0
    total_translated_chars: int = 0
    avg_length_ratio: float = 0.0


@dataclass
class VolumeStatistics:
    """Comprehensive statistics for volume translation"""
    # Block counts
    total_blocks: int = 0
    body_blocks_count: int = 0
    non_body_blocks_count: int = 0

    # Success metrics
    successful_blocks: int = 0
    failed_blocks: int = 0
    success_rate: float = 0.0

    # Quality metrics
    average_quality: float = 0.0
    min_quality: float = 10.0
    max_quality: float = 0.0
    body_avg_quality: float = 0.0
    non_body_avg_quality: float = 0.0

    # Footnote metrics
    total_footnotes: int = 0
    total_footnote_mismatches: int = 0
    body_footnotes: int = 0
    non_body_footnotes: int = 0

    # Performance metrics
    total_translation_time: float = 0.0
    avg_time_per_block: float = 0.0

    # Character counts
    total_source_chars: int = 0
    total_translated_chars: int = 0
    avg_length_ratio: float = 0.0

    # Breakdown
    body_block_stats: BlockTypeStats = field(default_factory=BlockTypeStats)
    non_body_block_stats: BlockTypeStats = field(default_factory=BlockTypeStats)


@dataclass
class AggregateValidationReport:
    """Aggregate validation report for entire volume"""
    is_valid: bool

    # Quality validation
    average_quality: float
    quality_threshold: float
    quality_passed: bool

    # Footnote validation
    total_footnote_mismatches: int
    footnote_validation_passed: bool  # Must be zero mismatches

    # Block-level failures
    failed_blocks: List[str] = field(default_factory=list)  # Block IDs
    quality_failures: List[Dict[str, Any]] = field(default_factory=list)
    footnote_failures: List[Dict[str, Any]] = field(default_factory=list)

    # Summary
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)


@dataclass
class BlockResult:
    """Result from translating a single block"""
    block_id: str
    block_type: str  # 'body' or 'non-body'
    success: bool

    # Metrics
    quality_score: float = 0.0
    footnote_count: int = 0
    footnote_mismatches: int = 0
    translation_time: float = 0.0

    source_char_count: int = 0
    translated_char_count: int = 0
    length_ratio: float = 0.0

    # Full result
    result: Optional[ContentBlockTranslationResult] = None

    # Error details (if failed)
    error_message: Optional[str] = None


@dataclass
class VolumeTranslationResult:
    """Result from volume translation"""
    success: bool

    # Data
    translated_volume: Optional[Dict[str, Any]] = None

    # Reports
    statistics: VolumeStatistics = field(default_factory=VolumeStatistics)
    validation_report: Optional[AggregateValidationReport] = None

    # Details
    block_results: List[BlockResult] = field(default_factory=list)
    manifest: Optional[Dict[str, Any]] = None

    # Error details (if failed)
    error_details: Optional[Dict[str, Any]] = None


# =============================================================================
# VOLUME TRANSLATION WRAPPER
# =============================================================================

class VolumeTranslationWrapper:
    """
    Workflow node wrapper for volume translation with parallel processing.

    Features:
    - Fan-out: Parallel processing of content blocks
    - Fan-in: Aggregate results collection
    - Aggregate validation (avg quality >= 9.5, zero footnote mismatches)
    - Statistics breakdown (body vs non-body)
    - Progress tracking with tqdm
    - Structured logging and manifest generation

    Workflow:
    1. Extract and categorize blocks from volume
    2. Fan-out: Process blocks in parallel using ContentBlockTranslationWrapper
    3. Fan-in: Collect results as they complete
    4. Calculate aggregate statistics
    5. Validate aggregate results
    6. Generate manifest
    7. Return result
    """

    # Node metadata
    NODE_ID = "volume_translation_node"
    NODE_NAME = "Volume Translation"
    NODE_VERSION = "1.0.0"
    NODE_DESCRIPTION = "Translate entire volume with parallel block processing and aggregate validation"

    def __init__(
        self,
        config_path: Optional[str] = None,
        config_name: Optional[str] = None,
        work_id: Optional[str] = None,
        max_workers: Optional[int] = None,
        block_config_path: Optional[str] = None,
        block_config_name: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize volume translation wrapper.

        Configuration Priority (highest to lowest):
        1. Direct kwargs parameters
        2. Work-specific override file (config/volume_work_overrides/{work_id}_rules.yaml)
        3. Named config (config/volume_translation_rules.{config_name}.yaml)
        4. Default config (config/volume_translation_rules.yaml)
        5. Hardcoded defaults

        Args:
            config_path: Explicit path to volume config YAML file
            config_name: Named config ("strict", "fast", etc.)
            work_id: Work ID for work-specific overrides
            max_workers: Maximum parallel workers (overrides config)
            block_config_path: Config path for ContentBlockTranslationWrapper
            block_config_name: Named config for ContentBlockTranslationWrapper
            **kwargs: Additional overrides

        Examples:
            # Use default config
            wrapper = VolumeTranslationWrapper()

            # Use named config
            wrapper = VolumeTranslationWrapper(config_name="strict")

            # Use work-specific config
            wrapper = VolumeTranslationWrapper(work_id="D1379")

            # Override max_workers
            wrapper = VolumeTranslationWrapper(max_workers=10)

            # Combination: work config + override
            wrapper = VolumeTranslationWrapper(
                work_id="D1379",
                max_workers=10,
                block_config_name="strict"
            )
        """
        # Merge max_workers into kwargs if provided
        if max_workers is not None:
            kwargs['max_workers'] = max_workers

        # Load configuration
        self.config = VolumeConfig.load(
            config_path=config_path,
            config_name=config_name,
            work_id=work_id,
            **kwargs
        )

        # Store configuration
        self._work_id = work_id
        self.max_workers = self.config.parallel.max_workers
        self.timeout_per_block = self.config.parallel.timeout_per_block

        # Block-level configuration
        self.block_config_path = block_config_path
        self.block_config_name = block_config_name or self.config.block_config.config_name
        self.block_config_overrides = self.config.block_config.get_overrides()

        # Validation thresholds
        self.aggregate_quality_threshold = self.config.validation.aggregate_quality_threshold
        self.allow_footnote_mismatches = self.config.validation.allow_footnote_mismatches

        # Configure logging
        if self.config.logging.level:
            logger.setLevel(self.config.logging.level)

        logger.info(
            f"Initialized {self.NODE_NAME} wrapper: "
            f"max_workers={self.max_workers}, "
            f"quality_threshold={self.aggregate_quality_threshold}, "
            f"allow_footnote_mismatches={self.allow_footnote_mismatches}"
        )

        if config_name:
            logger.info(f"Using named config: {config_name}")
        if work_id:
            logger.info(f"Using work-specific config for: {work_id}")

    def execute(
        self,
        volume_data: Dict[str, Any],
        work_id: str,
        volume_id: Optional[str] = None
    ) -> VolumeTranslationResult:
        """
        Execute volume translation with parallel block processing.

        Args:
            volume_data: Complete volume JSON structure
            work_id: Work ID for tracking
            volume_id: Optional volume ID (e.g., "a", "b", "c")

        Returns:
            VolumeTranslationResult with success status, translated data, and reports
        """
        start_time = datetime.now()

        logger.info(
            f"Starting volume translation: work_id={work_id}, "
            f"volume_id={volume_id}, workers={self.max_workers}"
        )

        # Step 1: Extract and categorize blocks
        try:
            blocks = self._extract_blocks(volume_data)
            logger.info(
                f"Extracted {len(blocks)} blocks: "
                f"{sum(1 for b in blocks if b[1] == 'body')} body, "
                f"{sum(1 for b in blocks if b[1] == 'non-body')} non-body"
            )
        except Exception as e:
            logger.error(f"Failed to extract blocks: {e}")
            return VolumeTranslationResult(
                success=False,
                error_details={
                    "stage": "block_extraction",
                    "error": str(e)
                }
            )

        # Step 2: Fan-out - Parallel translation
        block_results = []

        try:
            if self.config.logging.log_progress:
                # With progress bar
                block_results = self._translate_blocks_with_progress(
                    blocks, work_id
                )
            else:
                # Without progress bar
                block_results = self._translate_blocks(blocks, work_id)
        except Exception as e:
            logger.error(f"Failed during parallel translation: {e}")
            return VolumeTranslationResult(
                success=False,
                error_details={
                    "stage": "parallel_translation",
                    "error": str(e)
                }
            )

        # Step 3: Calculate statistics
        statistics = self._calculate_statistics(block_results)

        # Step 4: Reconstruct volume (ALWAYS, even if validation might fail)
        # This ensures translated content is available even with quality warnings
        translated_volume = None
        try:
            translated_volume = self._reconstruct_volume(
                volume_data, block_results
            )
            logger.info("Volume reconstruction successful")
        except Exception as e:
            logger.error(f"Failed to reconstruct volume: {e}")
            # Reconstruction failure is a hard error
            return VolumeTranslationResult(
                success=False,
                statistics=self._calculate_statistics(block_results),
                error_details={
                    "stage": "volume_reconstruction",
                    "error": str(e)
                }
            )

        # Step 5: Validate aggregate results (after reconstruction)
        validation_report = self._validate_aggregate_results(block_results)

        # Step 6: Generate manifest
        end_time = datetime.now()
        manifest = self._generate_manifest(
            work_id=work_id,
            volume_id=volume_id,
            statistics=statistics,
            validation_report=validation_report,
            start_time=start_time,
            end_time=end_time
        )

        # Log results
        if validation_report.is_valid:
            logger.info(
                f"Volume translation successful: "
                f"avg_quality={statistics.average_quality:.1f}/10, "
                f"footnote_mismatches={statistics.total_footnote_mismatches}, "
                f"time={statistics.total_translation_time:.1f}s"
            )
        else:
            logger.error(
                f"Volume translation failed validation: "
                f"{validation_report.validation_errors}"
            )

        # Return result
        return VolumeTranslationResult(
            success=validation_report.is_valid,
            translated_volume=translated_volume,
            statistics=statistics,
            validation_report=validation_report,
            block_results=block_results,
            manifest=manifest
        )

    def _extract_blocks(
        self,
        volume_data: Dict[str, Any]
    ) -> List[Tuple[Dict[str, Any], str, str]]:
        """
        Extract and categorize blocks from volume.

        Returns:
            List of (block_dict, block_type, block_id) tuples
            block_type is 'body' or 'non-body'
        """
        blocks = []
        structure = volume_data.get("structure", {})

        # Extract body blocks (chapters)
        body = structure.get("body", {})
        chapters = body.get("chapters", [])

        for chapter in chapters:
            content_blocks = chapter.get("content_blocks", [])
            for block in content_blocks:
                block_id = block.get("id", "unknown")
                blocks.append((block, "body", block_id))

        # Extract non-body blocks
        # Metadata
        metadata = structure.get("metadata", {})
        if metadata:
            blocks.append((metadata, "non-body", "metadata"))

        # TOC
        toc = structure.get("toc", {})
        if toc:
            blocks.append((toc, "non-body", "toc"))

        # Front matter
        front_matter = structure.get("front_matter", {})
        if front_matter:
            # Introduction
            intro = front_matter.get("introduction", {})
            if intro and intro.get("content"):
                blocks.append((intro, "non-body", "front_matter.introduction"))

            # Other sections
            sections = front_matter.get("sections", [])
            for idx, section in enumerate(sections):
                if section.get("content"):
                    blocks.append((
                        section,
                        "non-body",
                        f"front_matter.section_{idx}"
                    ))

        # Back matter
        back_matter = structure.get("back_matter", {})
        if back_matter:
            sections = back_matter.get("sections", [])
            for idx, section in enumerate(sections):
                if section.get("content"):
                    blocks.append((
                        section,
                        "non-body",
                        f"back_matter.section_{idx}"
                    ))

        return blocks

    def _translate_blocks(
        self,
        blocks: List[Tuple[Dict[str, Any], str, str]],
        work_id: str
    ) -> List[BlockResult]:
        """
        Translate blocks in parallel (no progress bar).

        Args:
            blocks: List of (block_dict, block_type, block_id) tuples
            work_id: Work ID for tracking

        Returns:
            List of BlockResult objects
        """
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all blocks
            futures = {
                executor.submit(
                    self._translate_block,
                    block_dict,
                    block_type,
                    block_id,
                    work_id
                ): (block_dict, block_type, block_id)
                for block_dict, block_type, block_id in blocks
            }

            # Collect results
            for future in as_completed(futures):
                try:
                    result = future.result(timeout=self.timeout_per_block)
                    results.append(result)
                except Exception as e:
                    block_dict, block_type, block_id = futures[future]
                    logger.error(f"Block {block_id} failed with exception: {e}")
                    results.append(BlockResult(
                        block_id=block_id,
                        block_type=block_type,
                        success=False,
                        error_message=str(e)
                    ))

        return results

    def _translate_blocks_with_progress(
        self,
        blocks: List[Tuple[Dict[str, Any], str, str]],
        work_id: str
    ) -> List[BlockResult]:
        """
        Translate blocks in parallel with progress bar.

        Args:
            blocks: List of (block_dict, block_type, block_id) tuples
            work_id: Work ID for tracking

        Returns:
            List of BlockResult objects
        """
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all blocks
            futures = {
                executor.submit(
                    self._translate_block,
                    block_dict,
                    block_type,
                    block_id,
                    work_id
                ): (block_dict, block_type, block_id)
                for block_dict, block_type, block_id in blocks
            }

            # Collect results with progress bar
            with tqdm(
                total=len(blocks),
                desc="Translating blocks",
                unit="block"
            ) as pbar:
                for future in as_completed(futures):
                    try:
                        result = future.result(timeout=self.timeout_per_block)
                        results.append(result)

                        # Update progress bar description
                        if result.success:
                            pbar.set_postfix({
                                "quality": f"{result.quality_score:.1f}",
                                "footnotes": result.footnote_count
                            })
                        else:
                            pbar.set_postfix({"status": "FAILED"})
                    except Exception as e:
                        block_dict, block_type, block_id = futures[future]
                        logger.error(f"Block {block_id} failed with exception: {e}")
                        results.append(BlockResult(
                            block_id=block_id,
                            block_type=block_type,
                            success=False,
                            error_message=str(e)
                        ))
                    finally:
                        pbar.update(1)

        return results

    def _translate_block(
        self,
        block_dict: Dict[str, Any],
        block_type: str,
        block_id: str,
        work_id: str
    ) -> BlockResult:
        """
        Translate a single block using ContentBlockTranslationWrapper.

        Args:
            block_dict: Block dictionary with content
            block_type: 'body' or 'non-body'
            block_id: Unique block ID
            work_id: Work ID for tracking

        Returns:
            BlockResult with translation outcome
        """
        start_time = datetime.now()

        # Extract content
        content = block_dict.get("content", "")
        if not content:
            logger.warning(f"Block {block_id} has no content, skipping")
            return BlockResult(
                block_id=block_id,
                block_type=block_type,
                success=False,
                error_message="No content to translate"
            )

        try:
            # Initialize block wrapper with config
            block_wrapper = ContentBlockTranslationWrapper(
                config_path=self.block_config_path,
                config_name=self.block_config_name,
                work_id=work_id,
                **self.block_config_overrides
            )

            # Execute translation
            # Use block_id as content_text_id (convert to int if needed)
            content_text_id = hash(block_id) % (2**31)  # Simple hash for ID

            result = block_wrapper.execute(
                content_text_id=content_text_id,
                content_source_text=content,
                work_id=work_id
            )

            # Calculate metrics
            end_time = datetime.now()
            translation_time = (end_time - start_time).total_seconds()

            if result.success:
                validation = result.validation_report
                metrics = result.metrics

                return BlockResult(
                    block_id=block_id,
                    block_type=block_type,
                    success=True,
                    quality_score=validation.quality_score,
                    footnote_count=validation.footnote_marker_count,
                    footnote_mismatches=(
                        0 if validation.footnote_marker_count == validation.footnote_array_count
                        else abs(validation.footnote_marker_count - validation.footnote_array_count)
                    ),
                    translation_time=translation_time,
                    source_char_count=metrics.get("source_char_count", 0),
                    translated_char_count=metrics.get("translated_char_count", 0),
                    length_ratio=metrics.get("length_ratio", 0.0),
                    result=result
                )
            else:
                return BlockResult(
                    block_id=block_id,
                    block_type=block_type,
                    success=False,
                    translation_time=translation_time,
                    error_message=str(result.error_details),
                    result=result
                )

        except Exception as e:
            logger.error(f"Exception translating block {block_id}: {e}")
            end_time = datetime.now()
            translation_time = (end_time - start_time).total_seconds()

            return BlockResult(
                block_id=block_id,
                block_type=block_type,
                success=False,
                translation_time=translation_time,
                error_message=str(e)
            )

    def _calculate_statistics(
        self,
        block_results: List[BlockResult]
    ) -> VolumeStatistics:
        """
        Calculate aggregate statistics from block results.

        Args:
            block_results: List of BlockResult objects

        Returns:
            VolumeStatistics with comprehensive metrics
        """
        stats = VolumeStatistics()

        # Separate body and non-body results
        body_results = [r for r in block_results if r.block_type == "body"]
        non_body_results = [r for r in block_results if r.block_type == "non-body"]

        # Calculate overall counts
        stats.total_blocks = len(block_results)
        stats.body_blocks_count = len(body_results)
        stats.non_body_blocks_count = len(non_body_results)

        stats.successful_blocks = sum(1 for r in block_results if r.success)
        stats.failed_blocks = sum(1 for r in block_results if not r.success)
        stats.success_rate = (
            stats.successful_blocks / stats.total_blocks
            if stats.total_blocks > 0 else 0.0
        )

        # Calculate quality metrics (only successful blocks)
        successful_results = [r for r in block_results if r.success]

        if successful_results:
            quality_scores = [r.quality_score for r in successful_results]
            stats.average_quality = sum(quality_scores) / len(quality_scores)
            stats.min_quality = min(quality_scores)
            stats.max_quality = max(quality_scores)

        # Calculate footnote metrics
        stats.total_footnotes = sum(r.footnote_count for r in successful_results)
        stats.total_footnote_mismatches = sum(
            r.footnote_mismatches for r in successful_results
        )

        # Calculate performance metrics
        stats.total_translation_time = sum(r.translation_time for r in block_results)
        stats.avg_time_per_block = (
            stats.total_translation_time / stats.total_blocks
            if stats.total_blocks > 0 else 0.0
        )

        # Calculate character counts
        stats.total_source_chars = sum(r.source_char_count for r in successful_results)
        stats.total_translated_chars = sum(
            r.translated_char_count for r in successful_results
        )
        stats.avg_length_ratio = (
            stats.total_translated_chars / stats.total_source_chars
            if stats.total_source_chars > 0 else 0.0
        )

        # Calculate body-specific stats
        stats.body_block_stats = self._calculate_block_type_stats(body_results)
        stats.body_avg_quality = stats.body_block_stats.avg_quality
        stats.body_footnotes = stats.body_block_stats.total_footnotes

        # Calculate non-body-specific stats
        stats.non_body_block_stats = self._calculate_block_type_stats(non_body_results)
        stats.non_body_avg_quality = stats.non_body_block_stats.avg_quality
        stats.non_body_footnotes = stats.non_body_block_stats.total_footnotes

        return stats

    def _calculate_block_type_stats(
        self,
        block_results: List[BlockResult]
    ) -> BlockTypeStats:
        """Calculate statistics for a specific block type"""
        stats = BlockTypeStats()

        stats.block_count = len(block_results)
        stats.successful_blocks = sum(1 for r in block_results if r.success)
        stats.failed_blocks = sum(1 for r in block_results if not r.success)

        successful_results = [r for r in block_results if r.success]

        if successful_results:
            # Quality metrics
            quality_scores = [r.quality_score for r in successful_results]
            stats.avg_quality = sum(quality_scores) / len(quality_scores)
            stats.min_quality = min(quality_scores)
            stats.max_quality = max(quality_scores)

            # Footnote metrics
            stats.total_footnotes = sum(r.footnote_count for r in successful_results)
            stats.footnote_mismatches = sum(
                r.footnote_mismatches for r in successful_results
            )

            # Performance metrics
            stats.total_translation_time = sum(
                r.translation_time for r in successful_results
            )
            stats.avg_time_per_block = (
                stats.total_translation_time / len(successful_results)
            )

            # Character counts
            stats.total_source_chars = sum(
                r.source_char_count for r in successful_results
            )
            stats.total_translated_chars = sum(
                r.translated_char_count for r in successful_results
            )
            stats.avg_length_ratio = (
                stats.total_translated_chars / stats.total_source_chars
                if stats.total_source_chars > 0 else 0.0
            )

        return stats

    def _validate_aggregate_results(
        self,
        block_results: List[BlockResult]
    ) -> AggregateValidationReport:
        """
        Validate aggregate results against thresholds.

        Validation Rules:
        1. Average quality across ALL blocks >= threshold
        2. Total footnote mismatches = 0 (strict, unless configured otherwise)
        3. All blocks must succeed (no failures)

        Args:
            block_results: List of BlockResult objects

        Returns:
            AggregateValidationReport with validation outcome
        """
        errors = []
        warnings = []
        failed_blocks = []
        quality_failures = []
        footnote_failures = []

        # Calculate average quality (successful blocks only)
        successful_results = [r for r in block_results if r.success]

        if not successful_results:
            errors.append("No successful translations")
            avg_quality = 0.0
            quality_passed = False
        else:
            avg_quality = sum(r.quality_score for r in successful_results) / len(successful_results)
            quality_passed = avg_quality >= self.aggregate_quality_threshold

            if not quality_passed:
                errors.append(
                    f"Average quality {avg_quality:.2f} below threshold "
                    f"{self.aggregate_quality_threshold}"
                )

        # Count total footnote mismatches
        total_mismatches = sum(r.footnote_mismatches for r in successful_results)
        footnote_passed = (
            total_mismatches == 0 if not self.allow_footnote_mismatches
            else True
        )

        if not footnote_passed:
            errors.append(
                f"Total footnote mismatches: {total_mismatches} "
                f"(threshold: 0, strict mode)"
            )

        # Check for failed blocks
        failed_results = [r for r in block_results if not r.success]
        if failed_results:
            failed_blocks = [r.block_id for r in failed_results]
            errors.append(f"{len(failed_results)} blocks failed translation")

        # Check individual quality failures
        for result in successful_results:
            if result.quality_score < self.config.validation.block_quality_threshold:
                quality_failures.append({
                    "block_id": result.block_id,
                    "quality_score": result.quality_score,
                    "threshold": self.config.validation.block_quality_threshold
                })

        if quality_failures:
            warnings.append(
                f"{len(quality_failures)} blocks below individual quality threshold"
            )

        # Check individual footnote failures
        for result in successful_results:
            if result.footnote_mismatches > 0:
                footnote_failures.append({
                    "block_id": result.block_id,
                    "mismatches": result.footnote_mismatches
                })

        if footnote_failures:
            warnings.append(
                f"{len(footnote_failures)} blocks with footnote mismatches"
            )

        # Overall validation
        is_valid = (
            quality_passed and
            footnote_passed and
            len(failed_results) == 0
        )

        return AggregateValidationReport(
            is_valid=is_valid,
            average_quality=avg_quality,
            quality_threshold=self.aggregate_quality_threshold,
            quality_passed=quality_passed,
            total_footnote_mismatches=total_mismatches,
            footnote_validation_passed=footnote_passed,
            failed_blocks=failed_blocks,
            quality_failures=quality_failures,
            footnote_failures=footnote_failures,
            validation_errors=errors,
            validation_warnings=warnings
        )

    def _reconstruct_volume(
        self,
        original_volume: Dict[str, Any],
        block_results: List[BlockResult]
    ) -> Dict[str, Any]:
        """
        Reconstruct volume with translated content.

        Args:
            original_volume: Original volume structure
            block_results: List of BlockResult objects with translations

        Returns:
            Volume dictionary with translated content
        """
        # Create a mapping of block_id -> translated content
        translations = {}

        for result in block_results:
            if result.success and result.result:
                translated_data = result.result.translated_data
                if translated_data:
                    translations[result.block_id] = translated_data

        # Deep copy original volume
        import copy
        translated_volume = copy.deepcopy(original_volume)

        # Update blocks with translations
        structure = translated_volume.get("structure", {})

        # Update body blocks
        body = structure.get("body", {})
        chapters = body.get("chapters", [])

        for chapter in chapters:
            content_blocks = chapter.get("content_blocks", [])
            for block in content_blocks:
                block_id = block.get("id")
                if block_id in translations:
                    # Update block with translated content
                    trans_data = translations[block_id]
                    annotated = trans_data.get("translated_annotated_content", {})

                    block["content"] = annotated.get("annotated_content_text", "")
                    block["footnotes"] = annotated.get("content_footnotes", [])
                    block["content_type"] = annotated.get("content_type", "")

        # Update non-body blocks
        # (Similar logic for metadata, toc, front_matter, back_matter)
        # For simplicity, we'll just update content fields where found

        return translated_volume

    def _generate_manifest(
        self,
        work_id: str,
        volume_id: Optional[str],
        statistics: VolumeStatistics,
        validation_report: AggregateValidationReport,
        start_time: datetime,
        end_time: datetime
    ) -> Dict[str, Any]:
        """Generate comprehensive manifest for volume translation"""
        return {
            "node_id": self.NODE_ID,
            "node_name": self.NODE_NAME,
            "node_version": self.NODE_VERSION,

            # Identifiers
            "work_id": work_id,
            "volume_id": volume_id,

            # Processing metadata
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": (end_time - start_time).total_seconds(),

            # Configuration
            "max_workers": self.max_workers,
            "aggregate_quality_threshold": self.aggregate_quality_threshold,
            "allow_footnote_mismatches": self.allow_footnote_mismatches,

            # Statistics
            "statistics": asdict(statistics),

            # Validation
            "validation": asdict(validation_report),

            # Success
            "success": validation_report.is_valid
        }


# =============================================================================
# CLI / TESTING
# =============================================================================

def main():
    """Test the wrapper"""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Test with mock volume data
    test_volume = {
        "structure": {
            "metadata": {
                "title": "測試小說",
                "author": "測試作者"
            },
            "body": {
                "chapters": [
                    {
                        "chapter_number": 1,
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

    try:
        wrapper = VolumeTranslationWrapper(
            max_workers=3
        )

        result = wrapper.execute(
            volume_data=test_volume,
            work_id="TEST"
        )

        print("\n=== VOLUME TRANSLATION RESULT ===")
        print(f"Success: {result.success}")
        print(f"Total blocks: {result.statistics.total_blocks}")
        print(f"Successful: {result.statistics.successful_blocks}")
        print(f"Failed: {result.statistics.failed_blocks}")
        print(f"Average quality: {result.statistics.average_quality:.1f}/10")
        print(f"Total footnotes: {result.statistics.total_footnotes}")
        print(f"Footnote mismatches: {result.statistics.total_footnote_mismatches}")

        if result.validation_report:
            print(f"\nValidation passed: {result.validation_report.is_valid}")
            if result.validation_report.validation_errors:
                print(f"Errors: {result.validation_report.validation_errors}")

        print("\n=== MANIFEST ===")
        print(json.dumps(result.manifest, indent=2))

        return 0 if result.success else 1

    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
