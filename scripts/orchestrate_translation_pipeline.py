#!/usr/bin/env python3
"""
Translation Pipeline Orchestrator

8-stage translation pipeline with cultural footnotes, cleanup, and EPUB generation:
- Stage 1 (BODY): Prompts + FootnoteContextAccumulator + suppress list
- Stage 2 (METADATA): Title/author translation (no footnotes)
- Stage 3 (TOC): Table of contents translation (no footnotes)
- Stage 4 (HEADINGS): Chapter heading translation (no footnotes)
- Stage 5 (SPECIAL): Front/back matter translation
- Stage 6 (CLEANUP): 6a (character removal) + 6b (triviality) + 6c (density diagnostic)
- Stage 7 (VALIDATION): Coverage and footnote integrity checks
- Stage 8 (EPUB): Build EPUB with series info from catalog

Usage:
    python scripts/orchestrate_translation_pipeline.py D1379
    python scripts/orchestrate_translation_pipeline.py D1379 --volume a
    python scripts/orchestrate_translation_pipeline.py D1379 --resume
    python scripts/orchestrate_translation_pipeline.py D1379 --start-stage 1 --end-stage 6
"""

import sys
import json
import re
import argparse
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.footnote_context import FootnoteContextAccumulator
from processors.translation_prompts import get_suppress_ideograms, get_genre_key, resolve_prompt_key
from processors.translator import TranslationService
from wrappers.content_block_translation_wrapper import (
    ContentBlockTranslationWrapper,
)

# Cleanup utilities
from utils.cleanup_character_footnotes import (
    CharacterFootnoteCleanup,
    CleanupConfig,
)
from utils.remove_trivial_footnotes import (
    TrivialFootnoteRemover,
    TrivialityConfig,
    _renumber_chapter_continuous,
    _reposition_markers,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# PIPELINE STAGES
# =============================================================================

class PipelineStage(Enum):
    """Translation pipeline stages"""
    BODY = (1, "body", "Translate body content - WITH cultural/historical footnotes")
    METADATA = (2, "metadata", "Translate metadata (title, author) - NO footnotes")
    TOC = (3, "toc", "Translate TOC - NO footnotes (clean navigation)")
    HEADINGS = (4, "headings", "Translate chapter headings (use TOC) - NO footnotes")
    SPECIAL = (5, "special", "Translate special sections - WITH footnotes")
    CLEANUP = (6, "cleanup", "Remove redundant character name footnotes")
    VALIDATION = (7, "validation", "Validate translation completeness and quality")
    EPUB = (8, "epub", "Build EPUB from translated JSON")

    def __init__(self, num: int, name: str, description: str):
        self.num = num
        self.stage_name = name
        self.description = description

    @property
    def wip_dir_name(self) -> str:
        return f"stage_{self.num}_{self.stage_name}"

    @property
    def log_suffix(self) -> str:
        return f"stage_{self.num}_{self.stage_name}"


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class OrchestrationConfig:
    """Orchestration configuration"""
    # Paths (defaults loaded from environment config)
    source_dir: Path = None
    output_dir: Path = None
    wip_dir: Path = None
    log_dir: Path = None
    catalog_path: Path = None

    # Translation settings
    model: Optional[str] = None
    temperature: float = 0.3
    max_retries: int = 2
    timeout: int = 120

    # Processing settings
    max_concurrent_chapters: int = 3
    max_workers: int = 5
    rate_limit_delay: float = 0.5
    skip_completed: bool = False
    dry_run: bool = False

    # Pipeline settings
    start_stage: int = 1
    end_stage: int = 8
    enable_ui_preview: bool = True
    enable_progress_tracking: bool = True

    # Footnote cleanup settings (Stage 6)
    enable_footnote_cleanup: bool = True
    footnote_batch_size: int = 25
    preserve_historical: bool = True
    preserve_legendary: bool = True
    preserve_cultural: bool = True

    # Genre-aware prompt selection
    genre: str = "wuxia"
    author: str = None  # author_chinese for style overlay

    verbose: bool = False

    # Library layout overrides (set by pipeline.run() when library/ exists)
    _library_wip_dir: Path = None
    _library_output_dir: Path = None
    _library_log_dir: Path = None
    _library_epub_dir: Path = None

    def __post_init__(self):
        # Load defaults from environment config for any paths not explicitly set
        from utils.environment_config import get_or_create_config
        env = get_or_create_config()
        if self.source_dir is None:
            self.source_dir = env.source_dir
        if self.output_dir is None:
            self.output_dir = env.output_dir
        if self.wip_dir is None:
            self.wip_dir = env.wip_dir
        if self.log_dir is None:
            self.log_dir = env.log_dir
        if self.catalog_path is None:
            self.catalog_path = env.catalog_path
        for directory in [self.output_dir, self.wip_dir, self.log_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def configure_library_paths(self, work_number: str, volume: Optional[str] = None):
        """Set library-layout paths for a specific work. Called by pipeline.run()."""
        from utils.environment_config import get_or_create_config
        env = get_or_create_config()

        if not env.use_library_layout:
            return  # library/ not yet created, use old paths

        wip = env.work_wip_dir(work_number, volume)
        if wip:
            self._library_wip_dir = wip
            wip.mkdir(parents=True, exist_ok=True)

        trans = env.work_translation_dir(work_number, volume)
        if trans:
            self._library_output_dir = trans
            trans.mkdir(parents=True, exist_ok=True)

        log = env.work_log_dir(work_number)
        if log:
            self._library_log_dir = log
            log.mkdir(parents=True, exist_ok=True)

        epub = env.work_epub_dir(work_number)
        if epub:
            self._library_epub_dir = epub
            epub.mkdir(parents=True, exist_ok=True)

    def get_stage_wip_dir(self, stage: PipelineStage) -> Path:
        if self._library_wip_dir:
            # In library layout, WIP files are flat in translation/wip/
            self._library_wip_dir.mkdir(parents=True, exist_ok=True)
            return self._library_wip_dir
        stage_dir = self.wip_dir / stage.wip_dir_name
        stage_dir.mkdir(parents=True, exist_ok=True)
        return stage_dir

    def get_stage_log_path(self, filename: str, stage: PipelineStage) -> Path:
        if self._library_log_dir:
            return self._library_log_dir / f"{stage.log_suffix}.json"
        return self.log_dir / f"{filename}_{stage.log_suffix}.json"

    def get_output_dir(self) -> Path:
        return self._library_output_dir or self.output_dir

    def get_epub_dir(self) -> Path:
        return self._library_epub_dir or self.epub_dir


# =============================================================================
# WIP MANAGER
# =============================================================================

class WIPManager:
    """Manages Work-In-Progress files across pipeline stages."""

    def __init__(self, config: OrchestrationConfig):
        self.config = config

    def _wip_path(self, filename: str, stage: PipelineStage) -> Path:
        """Resolve WIP file path. In library mode, uses stage name as filename."""
        wip_dir = self.config.get_stage_wip_dir(stage)
        if self.config._library_wip_dir:
            # Library layout: flat dir, stage-named files
            return wip_dir / f"{stage.wip_dir_name}.json"
        # Old layout: stage-named dirs, work-named files
        return wip_dir / f"{filename}.json"

    def save_wip(
        self, data: Dict[str, Any], filename: str, stage: PipelineStage,
        stage_log: Optional[Dict[str, Any]] = None,
    ) -> Path:
        wip_path = self._wip_path(filename, stage)

        if not self.config.dry_run:
            with open(wip_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved WIP: {wip_path}")
        else:
            logger.info(f"[DRY RUN] Would save WIP: {wip_path}")

        if stage_log:
            log_path = self.config.get_stage_log_path(filename, stage)
            if not self.config.dry_run:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, 'w', encoding='utf-8') as f:
                    json.dump(stage_log, f, ensure_ascii=False, indent=2)

        return wip_path

    def load_wip(self, filename: str, stage: PipelineStage) -> Optional[Dict[str, Any]]:
        wip_path = self._wip_path(filename, stage)
        if wip_path.exists():
            with open(wip_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        # Fall back to old-layout path if library path didn't match
        if self.config._library_wip_dir:
            old_dir = self.config.wip_dir / stage.wip_dir_name
            old_path = old_dir / f"{filename}.json"
            if old_path.exists():
                with open(old_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        return None

    def get_completed_stages(self, filename: str) -> List[PipelineStage]:
        completed = []
        for stage in PipelineStage:
            if self.load_wip(filename, stage) is not None:
                completed.append(stage)
        return completed

    def rollback_to_stage(self, filename: str, target_stage: PipelineStage) -> Optional[Dict[str, Any]]:
        logger.info(f"Rolling back to {target_stage.stage_name} (stage {target_stage.num})")
        return self.load_wip(filename, target_stage)


# =============================================================================
# STAGE PROCESSORS
# =============================================================================

class StageProcessor:
    """Base class for stage processors"""

    def __init__(self, config: OrchestrationConfig, wip_manager: WIPManager):
        self.config = config
        self.wip_manager = wip_manager

    def process(self, data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses must implement process()")

    def create_stage_log(
        self, stage: PipelineStage, start_time: datetime, end_time: datetime,
        items_processed: int, success: bool, errors: List[str] = None,
    ) -> Dict[str, Any]:
        duration = (end_time - start_time).total_seconds()
        return {
            "stage_number": stage.num,
            "stage_name": stage.stage_name,
            "description": stage.description,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "items_processed": items_processed,
            "success": success,
            "errors": errors or [],
        }


class MetadataTranslationProcessor(StageProcessor):
    """Stage 2: Translate metadata (NO footnotes)"""

    def process(self, data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        start_time = datetime.now()
        logger.info(f"Stage 2: Translating metadata for {filename}...")

        translator = TranslationService(
            model=self.config.model,
            temperature=self.config.temperature,
            genre=self.config.genre,
            author=self.config.author,
        )

        meta = data.get('meta', {})
        items_processed = 0
        errors = []

        if 'title_chinese' in meta and not meta.get('title_english'):
            try:
                title_response = translator.translate_from_dict({
                    "content_text_id": 0,
                    "content_source_text": meta['title_chinese'],
                })
                translated_content = title_response.get('translated_annotated_content', {})
                title_en = translated_content.get('annotated_content_text', '')
                meta['title_english'] = re.sub(r'\[\d+\]', '', title_en).strip()
                items_processed += 1
                logger.info(f"  Title: {meta['title_chinese']} -> {meta['title_english']}")
            except Exception as e:
                errors.append(f"Failed to translate title: {e}")

        if 'author_chinese' in meta and not meta.get('author_english'):
            try:
                author_response = translator.translate_from_dict({
                    "content_text_id": 1,
                    "content_source_text": meta['author_chinese'],
                })
                translated_content = author_response.get('translated_annotated_content', {})
                author_en = translated_content.get('annotated_content_text', '')
                meta['author_english'] = re.sub(r'\[\d+\]', '', author_en).strip()
                items_processed += 1
                logger.info(f"  Author: {meta['author_chinese']} -> {meta['author_english']}")
            except Exception as e:
                errors.append(f"Failed to translate author: {e}")

        data['meta'] = meta

        end_time = datetime.now()
        stage_log = self.create_stage_log(
            PipelineStage.METADATA, start_time, end_time,
            items_processed, success=len(errors) == 0, errors=errors,
        )
        self.wip_manager.save_wip(data, filename, PipelineStage.METADATA, stage_log)
        return data


class TOCTranslationProcessor(StageProcessor):
    """Stage 3: Translate TOC (NO footnotes)"""

    def process(self, data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        start_time = datetime.now()
        logger.info(f"Stage 3: Translating TOC for {filename}...")

        translator = TranslationService(
            model=self.config.model,
            temperature=self.config.temperature,
            genre=self.config.genre,
            author=self.config.author,
        )

        structure = data.get('structure', {})
        front_matter = structure.get('front_matter', {})
        toc = front_matter.get('toc', [])

        items_processed = 0
        errors = []

        for i, entry in enumerate(toc):
            if isinstance(entry, dict):
                full_title = entry.get('full_title', '')
                if entry.get('full_title_english'):
                    items_processed += 1
                    continue
                if full_title:
                    try:
                        response = translator.translate_from_dict({
                            "content_text_id": i,
                            "content_source_text": full_title,
                        })
                        translated_content = response.get('translated_annotated_content', {})
                        entry['full_title_english'] = translated_content.get('annotated_content_text', '')
                        items_processed += 1
                    except Exception as e:
                        errors.append(f"Failed to translate TOC entry {i}: {e}")

        if toc:
            front_matter['toc'] = toc
            structure['front_matter'] = front_matter
            data['structure'] = structure

        logger.info(f"  Translated {items_processed}/{len(toc)} TOC entries")

        end_time = datetime.now()
        stage_log = self.create_stage_log(
            PipelineStage.TOC, start_time, end_time,
            items_processed, success=len(errors) == 0, errors=errors,
        )
        self.wip_manager.save_wip(data, filename, PipelineStage.TOC, stage_log)
        return data


class HeadingTranslationProcessor(StageProcessor):
    """Stage 4: Translate chapter headings (use TOC, NO footnotes)"""

    def process(self, data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        start_time = datetime.now()
        logger.info(f"Stage 4: Translating chapter headings for {filename}...")

        toc = data.get('structure', {}).get('front_matter', {}).get('toc', [])
        toc_map = {}
        for entry in toc:
            if isinstance(entry, dict):
                chapter_num = entry.get('chapter_number')
                full_title_en = entry.get('full_title_english', '')
                if chapter_num and full_title_en:
                    toc_map[chapter_num] = full_title_en

        chapters = data.get('structure', {}).get('body', {}).get('chapters', [])
        items_processed = 0
        errors = []

        for chapter in chapters:
            chapter_num = chapter.get('chapter_number')
            title_chinese = chapter.get('title', '')

            if chapter.get('title_english'):
                items_processed += 1
                continue

            if chapter_num in toc_map:
                chapter['title_english'] = toc_map[chapter_num]
                items_processed += 1
            elif title_chinese:
                try:
                    translator = TranslationService(
                        model=self.config.model,
                        temperature=self.config.temperature,
                        genre=self.config.genre,
                        author=self.config.author,
                    )
                    response = translator.translate_from_dict({
                        "content_text_id": chapter_num or 0,
                        "content_source_text": title_chinese,
                    })
                    translated_content = response.get('translated_annotated_content', {})
                    chapter['title_english'] = translated_content.get('annotated_content_text', '')
                    items_processed += 1
                except Exception as e:
                    errors.append(f"Failed to translate chapter {chapter_num} heading: {e}")

        logger.info(f"  Translated {items_processed}/{len(chapters)} chapter headings")

        end_time = datetime.now()
        stage_log = self.create_stage_log(
            PipelineStage.HEADINGS, start_time, end_time,
            items_processed, success=len(errors) == 0, errors=errors,
        )
        self.wip_manager.save_wip(data, filename, PipelineStage.HEADINGS, stage_log)
        return data


def _sanitize_orphan_markers(data: Dict[str, Any]) -> int:
    """Strip [N] markers from translated text that have no matching footnote.

    Returns the number of blocks that had orphaned markers removed.
    """
    blocks_fixed = 0
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            text = block.get("translated_content", "")
            if not text:
                continue
            fns = block.get("footnotes", [])
            valid_keys = {str(fn.get("key")) for fn in fns}
            markers = set(re.findall(r"\[(\d+)\]", text))
            orphans = markers - valid_keys
            if orphans:
                def _strip(match):
                    return "" if match.group(1) in orphans else match.group(0)
                block["translated_content"] = re.sub(r"\[(\d+)\]", _strip, text)
                blocks_fixed += 1
    return blocks_fixed


# =============================================================================
# BODY TRANSLATION PROCESSOR (Stage 1)
# =============================================================================

class BodyTranslationProcessor(StageProcessor):
    """
    Stage 1: Translate body content.

    Uses ContentBlockTranslationWrapper which provides:
    - Prompts (suppress list, anti-spoiler, no character name footnotes)
    - FootnoteContextAccumulator for cross-block dedup
    - Dedup-aware glossary context
    - Density diagnostic logging

    Parallelism: Blocks within a chapter translate in parallel, but
    accumulator registration happens in block order after all blocks
    in a chapter complete.
    """

    def __init__(
        self,
        config: OrchestrationConfig,
        wip_manager: WIPManager,
        accumulator: FootnoteContextAccumulator,
    ):
        super().__init__(config, wip_manager)
        self.accumulator = accumulator

    def process(self, data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        start_time = datetime.now()
        logger.info(f"Stage 1: Translating body content for {filename}...")

        meta = data.get("meta", {})
        work_number = meta.get("work_number", "UNKNOWN")
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        wrapper = ContentBlockTranslationWrapper(
            accumulator=self.accumulator,
            model=self.config.model,
            temperature=self.config.temperature,
            max_retries=self.config.max_retries,
            timeout=self.config.timeout,
            genre=self.config.genre,
            author=self.config.author,
        )

        total_blocks = 0
        successful_blocks = 0
        total_footnotes = 0
        errors = []

        for ch_idx, chapter in enumerate(chapters):
            ch_num = ch_idx + 1
            content_blocks = chapter.get("content_blocks", [])
            translatable = [
                b for b in content_blocks
                if b.get("type") in [
                    "text", "paragraph", "narrative", "dialogue",
                    "verse", "document", "thought", "descriptive",
                ]
                and b.get("content", "").strip()
            ]

            logger.info(
                f"  Chapter {ch_num}/{len(chapters)}: "
                f"{len(translatable)}/{len(content_blocks)} translatable blocks"
            )

            # Translate blocks in parallel within chapter
            results_map = {}
            with ThreadPoolExecutor(
                max_workers=self.config.max_concurrent_chapters
            ) as executor:
                futures = {}
                for block_idx, block in enumerate(translatable):
                    future = executor.submit(
                        wrapper.execute,
                        content_text_id=block_idx + 1,
                        content_source_text=block["content"],
                        work_id=work_number,
                        chapter_num=ch_num,
                    )
                    futures[future] = block

                for future in as_completed(futures):
                    block = futures[future]
                    block_id = block.get("id", "unknown")
                    try:
                        result = future.result()
                        results_map[block_id] = result
                    except Exception as e:
                        logger.error(f"Block {block_id} failed: {e}")
                        errors.append(f"Block {block_id}: {e}")

            # Apply translations to blocks (in order for accumulator)
            for block in content_blocks:
                block_id = block.get("id")
                result = results_map.get(block_id)
                total_blocks += 1

                if result and result.success:
                    annotated = result.translated_data.get(
                        "translated_annotated_content", {}
                    )
                    block["translated_content"] = annotated.get(
                        "annotated_content_text", ""
                    )
                    block["footnotes"] = [
                        {
                            "key": fn["footnote_key"],
                            "ideogram": fn["footnote_details"]["footnote_ideogram"],
                            "pinyin": fn["footnote_details"]["footnote_pinyin"],
                            "explanation": fn["footnote_details"]["footnote_explanation"],
                        }
                        for fn in annotated.get("content_footnotes", [])
                    ]
                    block["content_type"] = annotated.get(
                        "content_type", "narrative"
                    )
                    successful_blocks += 1
                    total_footnotes += len(block["footnotes"])

            # Rate limiting between chapters
            time.sleep(self.config.rate_limit_delay)

        logger.info(
            f"  Body translation complete: {successful_blocks}/{total_blocks} blocks, "
            f"{total_footnotes} footnotes, {self.accumulator.total_registered} unique terms"
        )

        end_time = datetime.now()
        stage_log = self.create_stage_log(
            PipelineStage.BODY, start_time, end_time,
            successful_blocks, success=len(errors) == 0, errors=errors,
        )
        self.wip_manager.save_wip(data, filename, PipelineStage.BODY, stage_log)
        return data


# =============================================================================
# CLEANUP PROCESSOR (Stage 6)
# =============================================================================

class CleanupProcessor(StageProcessor):
    """
    Stage 6: Expanded footnote cleanup.

    6a: Character footnote removal (AI classification)
    6b: Triviality removal + work-wide dedup
    6c: Duplicate-topic footnote removal (programmatic ideogram overlap detection)
    Renumber and reposition after all phases.
    """

    def process(self, data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        start_time = datetime.now()
        logger.info(f"Stage 6: Footnote cleanup for {filename}...")

        errors = []
        total_removed = 0

        # 6a: Character footnote removal
        logger.info("  6a: Character footnote removal...")
        try:
            cleanup_kwargs = dict(
                batch_size=self.config.footnote_batch_size,
                preserve_historical=self.config.preserve_historical,
                preserve_legendary=self.config.preserve_legendary,
                preserve_cultural=self.config.preserve_cultural,
                create_backup=False,
            )
            if self.config.model is not None:
                cleanup_kwargs["model"] = self.config.model
            cleanup_config = CleanupConfig(**cleanup_kwargs)
            cleanup = CharacterFootnoteCleanup(cleanup_config)
            footnotes_all = cleanup.extract_all_footnotes(data)
            if footnotes_all:
                classifications = cleanup.classify_all_footnotes(footnotes_all)
                data = cleanup.cleanup_footnotes(data, classifications)
                removed_6a = cleanup.result.removed_count
                total_removed += removed_6a
                logger.info(f"    6a removed {removed_6a} fictional character footnotes")
            else:
                logger.info("    6a: no footnotes to process")
        except Exception as e:
            logger.error(f"    6a failed: {e}")
            errors.append(f"6a: {e}")

        # 6b: Triviality removal + dedup
        logger.info("  6b: Triviality removal + dedup...")
        try:
            triviality_kwargs = dict(
                batch_size=10,
                triviality_threshold=60,
                cultural_threshold=40,
                create_backup=False,
            )
            if self.config.model is not None:
                triviality_kwargs["model"] = self.config.model
            triviality_config = TrivialityConfig(**triviality_kwargs)
            remover = TrivialFootnoteRemover(triviality_config)
            footnotes_remaining = remover.extract_footnotes_with_context(data)
            if footnotes_remaining:
                scores = remover.score_all_footnotes(footnotes_remaining)
                data = remover.remove_trivial_footnotes(data, scores)
                removed_6b = remover.result.removed_count
                total_removed += removed_6b
                logger.info(
                    f"    6b removed {removed_6b} footnotes "
                    f"({remover.result.duplicate_count} duplicates)"
                )
            else:
                logger.info("    6b: no footnotes to process")
        except Exception as e:
            logger.error(f"    6b failed: {e}")
            errors.append(f"6b: {e}")

        # 6c: AI review — remove plot/character description footnotes
        logger.info("  6c: Dedup + plot footnote review (mini)...")
        try:
            removed_6c = self._review_plot_footnotes(data)
            total_removed += removed_6c
            if removed_6c:
                logger.info(f"    6c removed {removed_6c} plot/character footnotes")
            else:
                logger.info("    6c: no plot footnotes found")
        except Exception as e:
            logger.error(f"    6c failed: {e}")
            errors.append(f"6c: {e}")

        # Reposition misplaced markers (e.g. mid-word splits like Wǔ[14]zǐ)
        logger.info("  Repositioning misplaced markers...")
        repos_count, unanchored_count = _reposition_markers(data)
        if repos_count:
            logger.info(f"    Repositioned {repos_count} footnote markers")
        if unanchored_count:
            logger.info(f"    Removed {unanchored_count} unanchored footnotes")

        # Renumber footnotes continuously across each chapter
        logger.info("  Renumbering footnotes chapter-continuously...")
        _renumber_chapter_continuous(data)

        # Final pass: strip any orphaned [N] markers left after cleanup
        logger.info("  Sanitizing orphaned markers...")
        orphans_stripped = _sanitize_orphan_markers(data)
        if orphans_stripped:
            logger.info(f"    Stripped orphaned markers from {orphans_stripped} blocks")

        logger.info(f"  Cleanup complete: {total_removed} total footnotes removed")

        end_time = datetime.now()
        stage_log = self.create_stage_log(
            PipelineStage.CLEANUP, start_time, end_time,
            total_removed, success=len(errors) == 0, errors=errors,
        )
        self.wip_manager.save_wip(data, filename, PipelineStage.CLEANUP, stage_log)
        return data

    def _review_plot_footnotes(self, data: Dict[str, Any]) -> int:
        """
        6c: Two-pass footnote review.

        Pass 1 (programmatic): Remove duplicate-topic footnotes. If two footnotes
        explain the same concept (overlapping ideograms), keep the first and
        remove later occurrences.

        Pass 2 (AI): Send surviving footnotes to nano for per-footnote KEEP/REMOVE
        classification, targeting plot summaries and character descriptions.

        Returns total count of removed footnotes.
        """
        from openai import OpenAI

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        removed = 0

        # ── Pass 1: Programmatic duplicate-topic removal ──
        # Track ideograms we've already explained. If a later footnote's ideogram
        # is a substring of an earlier one (楚 ⊂ 楚國) or vice versa, remove the
        # later occurrence.
        # NOTE: We track by (block, fn) identity, NOT fn["key"], because keys
        # are per-block and may all be 1 before renumbering.
        seen_ideograms: dict[str, tuple] = {}  # ideogram → (block, fn) of first
        dup_fns: list[tuple] = []  # list of (block, fn) to remove

        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                for fn in block.get("footnotes", []):
                    ideo = fn.get("ideogram", "").strip()
                    if not ideo:
                        continue

                    is_dup = False
                    for seen_ideo in seen_ideograms:
                        if ideo in seen_ideo or seen_ideo in ideo:
                            is_dup = True
                            break

                    if is_dup:
                        dup_fns.append((block, fn))
                    else:
                        seen_ideograms[ideo] = (block, fn)

        if dup_fns:
            from collections import defaultdict
            block_dup_fns = defaultdict(list)
            for block, fn in dup_fns:
                block_dup_fns[id(block)].append(fn)

            for chapter in chapters:
                for block in chapter.get("content_blocks", []):
                    fns_to_remove = block_dup_fns.get(id(block))
                    if not fns_to_remove:
                        continue
                    remove_set = {id(fn) for fn in fns_to_remove}
                    text = block.get("translated_content", "")
                    surviving = []
                    for fn in block.get("footnotes", []):
                        if id(fn) in remove_set:
                            text = text.replace(f'[{fn["key"]}]', "")
                            removed += 1
                        else:
                            surviving.append(fn)
                    block["footnotes"] = surviving
                    block["translated_content"] = text
            logger.info(f"    6c dedup: removed {len(dup_fns)} duplicate-topic footnotes")

        # ── Pass 2: AI review for plot/character footnotes (gpt-4.1-mini) ──
        # Use sequential index (not fn["key"] which may collide across blocks)
        surviving_fns = []
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                for fn in block.get("footnotes", []):
                    surviving_fns.append((block, fn))

        if not surviving_fns:
            return removed

        fn_lines = [
            f'{idx}. {fn.get("ideogram", "")} — {fn.get("explanation", "")}'
            for idx, (_, fn) in enumerate(surviving_fns, 1)
        ]

        preamble = (
            "These footnotes are from a translated Chinese historical novel. "
            "I want to KEEP most of them. I ONLY want to remove footnotes that "
            "spoil the plot or describe fictional characters.\n\n"
            "EXAMPLES OF WHAT TO KEEP:\n"
            '- "Gōu Jiàn was the King of Yuè during the Spring and Autumn '
            'period" → KEEP (real historical figure)\n'
            '- "A jīn is approximately 500 grams" → KEEP (unit of measure)\n'
            '- "Mògān Shān is a mountain in Zhèjiāng province" → KEEP (real place)\n'
            '- "Xī Shī is one of the Four Beauties of ancient China" → KEEP\n'
            '- "Dàfū was an official rank in ancient China" → KEEP (title)\n\n'
            "EXAMPLES OF WHAT TO REMOVE:\n"
            '- "Ā Qīng is a personal name, here referring to a formidable '
            'martial artist whose prowess..." → REMOVE (fictional character '
            "description, plot spoiler)\n"
            '- "Yí Guāng is a personal name, here referring to a palace maid '
            'whose identity is pivotal to the plot" → REMOVE (plot spoiler)\n'
            '- "A nickname meaning Wind Beard, here it refers to a rugged '
            'character" → REMOVE (fictional character description)\n\n'
            "For each footnote, output: number. KEEP or number. REMOVE\n"
            "When in doubt, KEEP.\n\nFOOTNOTES:\n"
        )

        client = OpenAI()
        batch_size = 30
        remove_keys: set[int] = set()

        for i in range(0, len(fn_lines), batch_size):
            batch = fn_lines[i:i + batch_size]
            resp = client.chat.completions.create(
                model="gpt-4.1-mini",
                temperature=0.1,
                messages=[{"role": "user", "content": preamble + "\n".join(batch)}],
            )
            result = resp.choices[0].message.content.strip()
            for line in result.split("\n"):
                m = re.match(r"(\d+)\.\s*(REMOVE|KEEP)", line.strip())
                if m and m.group(2) == "REMOVE":
                    remove_keys.add(int(m.group(1)))

        if remove_keys:
            # Map sequential indices back to (block, fn) pairs
            to_remove = []
            for idx, (block, fn) in enumerate(surviving_fns, 1):
                if idx in remove_keys:
                    to_remove.append((block, fn))

            # Group removals by block for efficient processing
            from collections import defaultdict
            block_removals = defaultdict(list)
            for block, fn in to_remove:
                block_removals[id(block)].append(fn)

            for chapter in chapters:
                for block in chapter.get("content_blocks", []):
                    fns_to_remove = block_removals.get(id(block))
                    if not fns_to_remove:
                        continue
                    remove_fn_keys = {fn["key"] for fn in fns_to_remove}
                    text = block.get("translated_content", "")
                    surviving = []
                    for fn in block.get("footnotes", []):
                        if fn["key"] in remove_fn_keys:
                            text = text.replace(f'[{fn["key"]}]', "")
                            removed += 1
                        else:
                            surviving.append(fn)
                    block["footnotes"] = surviving
                    block["translated_content"] = text

            logger.info(
                f"    6c AI review: removed {len(remove_keys)} plot/character footnotes"
            )

        return removed


# =============================================================================
# SPECIAL SECTIONS PROCESSOR (Stage 5)
# =============================================================================

class SpecialSectionProcessor(StageProcessor):
    """Stage 5: Translate special sections (front_matter, back_matter)."""

    def process(self, data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        start_time = datetime.now()
        logger.info(f"Stage 5: Translating special sections for {filename}...")

        translator = TranslationService(
            model=self.config.model,
            temperature=self.config.temperature,
            genre=self.config.genre,
            author=self.config.author,
        )

        items_processed = 0
        errors = []

        # Process front_matter introduction
        structure = data.get("structure", {})
        front_matter = structure.get("front_matter", {})
        intro = front_matter.get("introduction", {})

        if intro and intro.get("content") and not intro.get("translated_content"):
            try:
                response = translator.translate_from_dict({
                    "content_text_id": 9000,
                    "content_source_text": intro["content"],
                })
                annotated = response.get("translated_annotated_content", {})
                intro["translated_content"] = annotated.get("annotated_content_text", "")
                items_processed += 1
            except Exception as e:
                errors.append(f"Introduction: {e}")

        # Process back_matter sections
        back_matter = structure.get("back_matter", {})
        for idx, section in enumerate(back_matter.get("sections", [])):
            if section.get("content") and not section.get("translated_content"):
                try:
                    response = translator.translate_from_dict({
                        "content_text_id": 9100 + idx,
                        "content_source_text": section["content"],
                    })
                    annotated = response.get("translated_annotated_content", {})
                    section["translated_content"] = annotated.get("annotated_content_text", "")
                    items_processed += 1
                except Exception as e:
                    errors.append(f"Back matter section {idx}: {e}")

        logger.info(f"  Translated {items_processed} special sections")

        end_time = datetime.now()
        stage_log = self.create_stage_log(
            PipelineStage.SPECIAL, start_time, end_time,
            items_processed, success=len(errors) == 0, errors=errors,
        )
        self.wip_manager.save_wip(data, filename, PipelineStage.SPECIAL, stage_log)
        return data


# =============================================================================
# VALIDATION PROCESSOR (Stage 7)
# =============================================================================

class ValidationProcessor(StageProcessor):
    """Stage 7: Validate translation completeness and footnote integrity."""

    def process(self, data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        start_time = datetime.now()
        logger.info(f"Stage 7: Validating translation for {filename}...")

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        issues = []
        total_blocks = 0
        translated_blocks = 0
        total_footnotes = 0

        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                total_blocks += 1
                if block.get("translated_content"):
                    translated_blocks += 1
                total_footnotes += len(block.get("footnotes", []))

        coverage = translated_blocks / total_blocks * 100 if total_blocks else 0

        if coverage < 90:
            issues.append(
                f"Low translation coverage: {coverage:.1f}% "
                f"({translated_blocks}/{total_blocks} blocks)"
            )

        # Footnote integrity check
        from utils.remove_trivial_footnotes import validate_footnote_integrity
        integrity = validate_footnote_integrity(data)
        if not integrity["passed"]:
            issues.extend(integrity["errors"][:10])

        logger.info(
            f"  Coverage: {coverage:.1f}% ({translated_blocks}/{total_blocks})"
        )
        logger.info(f"  Total footnotes: {total_footnotes}")
        logger.info(
            f"  Footnote integrity: {'PASSED' if integrity['passed'] else 'FAILED'}"
        )
        if issues:
            for issue in issues[:5]:
                logger.warning(f"  Issue: {issue}")

        # Add validation results to meta
        if "translation" not in data.get("meta", {}):
            data.setdefault("meta", {})["translation"] = {}
        data["meta"]["translation"]["validation"] = {
            "coverage_pct": round(coverage, 1),
            "total_blocks": total_blocks,
            "translated_blocks": translated_blocks,
            "total_footnotes": total_footnotes,
            "footnote_integrity": integrity["passed"],
            "issues": issues,
        }

        end_time = datetime.now()
        stage_log = self.create_stage_log(
            PipelineStage.VALIDATION, start_time, end_time,
            total_blocks, success=len(issues) == 0, errors=issues,
        )
        self.wip_manager.save_wip(data, filename, PipelineStage.VALIDATION, stage_log)
        return data


# =============================================================================
# EPUB PROCESSOR (Stage 8)
# =============================================================================

class EpubProcessor(StageProcessor):
    """Stage 8: Build EPUB from translated and cleaned JSON."""

    def process(self, data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        start_time = datetime.now()
        logger.info(f"Stage 8: Building EPUB for {filename}...")

        from processors.epub_builder import EpubBuilder

        builder = EpubBuilder()
        output_dir = self.config.get_epub_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = builder._english_epub_path(data, output_dir)
        result = builder.build_from_data(data, output_path)

        size_kb = result.stat().st_size / 1024
        logger.info(f"  EPUB generated: {result.name} ({size_kb:.1f} KB)")

        end_time = datetime.now()
        stage_log = self.create_stage_log(
            PipelineStage.EPUB, start_time, end_time,
            1, success=True, errors=[],
        )
        stage_log["epub_path"] = str(result)
        self.wip_manager.save_wip(data, filename, PipelineStage.EPUB, stage_log)
        return data


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================

class TranslationPipeline:
    """
    Pipeline Orchestrator.

    Stage order:
    1. BODY       - Wrapper (prompts + accumulator + suppress list)
    2. METADATA   - Title/author translation
    3. TOC        - Table of contents translation
    4. HEADINGS   - Chapter heading translation
    5. SPECIAL    - Front/back matter translation
    6. CLEANUP    - Footnote cleanup (6a + 6b + 6c)
    7. VALIDATION - Coverage + integrity checks
    8. EPUB       - Build EPUB from translated JSON
    """

    def __init__(self, config: OrchestrationConfig):
        self.config = config
        self.wip_manager = WIPManager(config)

    def run(
        self,
        work_number: str,
        volume: Optional[str] = None,
        resume: bool = False,
        accumulator: Optional[FootnoteContextAccumulator] = None,
        chapter_limit: int = 0,
    ) -> Dict[str, Any]:
        """
        Run the translation pipeline for a single volume.

        Args:
            work_number: Work number (e.g., "D1379")
            volume: Volume letter (e.g., "a")
            resume: Whether to resume from last completed stage
            accumulator: Shared accumulator for multi-volume works

        Returns:
            Pipeline result dict
        """
        start_time = datetime.now()
        accumulator = accumulator or FootnoteContextAccumulator()

        # Configure library-layout paths for this work
        self.config.configure_library_paths(work_number, volume)

        # Find source file
        source_file = self._find_source_file(work_number, volume)
        if not source_file:
            return {"success": False, "error": f"Source file not found for {work_number}"}

        filename = source_file.stem
        logger.info(f"Pipeline: {work_number} ({filename})")

        # Load data
        with open(source_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Resolve prompt key from author + category
        meta = data.get("meta", {})
        category = meta.get("category_english") or meta.get("category", "")
        author_chinese = meta.get("author_chinese") or meta.get("author", "")

        # If category missing from meta, look up from DuckDB catalog
        if not category and self.config.catalog_path and self.config.catalog_path.exists():
            try:
                import duckdb
                conn = duckdb.connect(str(self.config.catalog_path), read_only=True)
                row = conn.execute(
                    "SELECT category_english, author_chinese FROM works WHERE work_number = ?",
                    [work_number],
                ).fetchone()
                conn.close()
                if row:
                    if row[0] and not category:
                        category = row[0]
                        logger.info(f"Catalog lookup: category_english='{category}'")
                    if row[1] and not author_chinese:
                        author_chinese = row[1]
                        logger.info(f"Catalog lookup: author_chinese='{author_chinese}'")
            except Exception as e:
                logger.warning(f"Catalog lookup failed: {e}")
        # Enrich meta with work_number and missing fields for downstream stages
        if not meta.get("work_number"):
            meta["work_number"] = work_number
        if not meta.get("title_chinese") and meta.get("title"):
            meta["title_chinese"] = meta["title"]
        if not meta.get("author") and author_chinese:
            meta["author"] = author_chinese
        data["meta"] = meta

        prompt_key = resolve_prompt_key(author_chinese, category)
        # Store both for downstream use — genre as fallback, author for overlay
        self.config.genre = prompt_key if prompt_key in ("wuxia", "classical") else get_genre_key(category)
        self.config.author = author_chinese or None
        logger.info(
            f"Prompt: author='{author_chinese or 'unknown'}', "
            f"category='{category}' → prompt_key='{prompt_key}'"
        )

        # Limit chapters if requested (for testing)
        if chapter_limit > 0:
            chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
            if len(chapters) > chapter_limit:
                logger.info(f"Limiting to first {chapter_limit} of {len(chapters)} chapters")
                data["structure"]["body"]["chapters"] = chapters[:chapter_limit]

        # Determine start stage
        start_stage = self.config.start_stage
        if resume:
            completed = self.wip_manager.get_completed_stages(filename)
            if completed:
                last_completed = max(s.num for s in completed)
                start_stage = last_completed + 1
                logger.info(f"Resuming from stage {start_stage}")
                # Load WIP from last completed stage
                last_stage = [s for s in PipelineStage if s.num == last_completed][0]
                wip_data = self.wip_manager.load_wip(filename, last_stage)
                if wip_data:
                    data = wip_data

        # When starting from a later stage (not resume), load the most recent WIP
        if not resume and start_stage > 1:
            # Try to load WIP from the stage just before start_stage
            for prev_num in range(start_stage - 1, 0, -1):
                prev_stage = [s for s in PipelineStage if s.num == prev_num][0]
                wip_data = self.wip_manager.load_wip(filename, prev_stage)
                if wip_data:
                    logger.info(f"Loaded WIP from stage {prev_num} ({prev_stage.stage_name})")
                    data = wip_data
                    break

        # Re-apply meta enrichment after WIP load (WIP may lack work_number etc.)
        meta = data.get("meta", {})
        if not meta.get("work_number"):
            meta["work_number"] = work_number
        if not meta.get("title_chinese") and meta.get("title"):
            meta["title_chinese"] = meta["title"]
        if not meta.get("author") and author_chinese:
            meta["author"] = author_chinese
        data["meta"] = meta

        # Build stage processors
        processors = {
            1: BodyTranslationProcessor(self.config, self.wip_manager, accumulator),
            2: MetadataTranslationProcessor(self.config, self.wip_manager),
            3: TOCTranslationProcessor(self.config, self.wip_manager),
            4: HeadingTranslationProcessor(self.config, self.wip_manager),
            5: SpecialSectionProcessor(self.config, self.wip_manager),
            6: CleanupProcessor(self.config, self.wip_manager),
            7: ValidationProcessor(self.config, self.wip_manager),
            8: EpubProcessor(self.config, self.wip_manager),
        }

        # Run stages
        stage_results = []
        for stage_num in range(start_stage, self.config.end_stage + 1):
            stage = [s for s in PipelineStage if s.num == stage_num][0]
            processor = processors.get(stage_num)

            if not processor:
                logger.warning(f"No processor for stage {stage_num}")
                continue

            logger.info(f"\n{'='*60}")
            logger.info(f"Stage {stage_num}: {stage.description}")
            logger.info(f"{'='*60}")

            try:
                data = processor.process(data, filename)
                stage_results.append({
                    "stage": stage_num,
                    "name": stage.stage_name,
                    "success": True,
                })
            except Exception as e:
                logger.error(f"Stage {stage_num} failed: {e}")
                stage_results.append({
                    "stage": stage_num,
                    "name": stage.stage_name,
                    "success": False,
                    "error": str(e),
                })
                break

        # Save final output
        if not self.config.dry_run:
            out_dir = self.config.get_output_dir()
            vol_suffix = volume or ""
            output_path = out_dir / f"{work_number}{vol_suffix}.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"\nFinal output: {output_path}")

            # Also save to old location for backward compat
            if self.config._library_output_dir:
                old_path = self.config.output_dir / f"translated_{filename}.json"
                old_path.parent.mkdir(parents=True, exist_ok=True)
                with open(old_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

            # Write/update status.json
            self._update_status(work_number, volume, stage_results)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        result = {
            "success": all(r["success"] for r in stage_results),
            "work_number": work_number,
            "volume": volume,
            "filename": filename,
            "stages": stage_results,
            "duration_seconds": duration,
            "accumulator_terms": accumulator.total_registered,
        }

        logger.info(f"\nPipeline complete: {duration/60:.1f} minutes")
        return result

    def _update_status(
        self, work_number: str, volume: Optional[str],
        stage_results: List[Dict[str, Any]],
    ):
        """Write or update status.json for the work."""
        from utils.environment_config import get_or_create_config
        env = get_or_create_config()

        if not env.use_library_layout:
            return

        from utils.library_path_resolver import resolve_work_info, build_status_json
        info = resolve_work_info(work_number, self.config.catalog_path)
        if not info:
            return

        status_path = env.library_dir / info.relative_path / "status.json"

        # Load existing status or create new
        if status_path.exists():
            with open(status_path, "r", encoding="utf-8") as f:
                status = json.load(f)
        else:
            status = build_status_json(work_number, self.config.catalog_path) or {}

        # Update completed stages
        completed = set(status.get("stages_completed", []))
        for sr in stage_results:
            if sr.get("success"):
                completed.add(sr["stage"])
        status["stages_completed"] = sorted(completed)
        status["last_run"] = datetime.now().isoformat()

        status_path.parent.mkdir(parents=True, exist_ok=True)
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated status: {status_path}")

    def _find_source_file(
        self, work_number: str, volume: Optional[str] = None
    ) -> Optional[Path]:
        """Find source JSON file for a work/volume.

        Checks library/ layout first, then falls back to old cleaned/ layout.
        """
        from utils.environment_config import get_or_create_config
        env = get_or_create_config()

        # 1. Try library layout: library/{path}/[vol_X/]cleaned/
        cleaned = env.work_cleaned_path(work_number, volume)
        if cleaned and cleaned.exists():
            logger.info(f"Found source in library: {cleaned}")
            return cleaned

        # 2. Fall back to old layout
        source_dir = self.config.source_dir
        patterns = []
        if volume:
            patterns.append(f"*{work_number}*{volume}*.json")
            patterns.append(f"*{work_number}{volume}*.json")
        patterns.append(f"*{work_number}*.json")

        for pattern in patterns:
            matches = list(source_dir.rglob(pattern))
            if matches:
                return matches[0]

        logger.error(f"No source file found for {work_number} in library/ or {source_dir}")
        return None


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Translation Pipeline Orchestrator"
    )
    parser.add_argument(
        "work_number",
        help="Work number to translate (e.g., D1379)",
    )
    parser.add_argument(
        "--volume", "-v",
        help="Volume letter (e.g., a, b, c)",
    )
    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="Resume from last completed stage",
    )
    parser.add_argument(
        "--start-stage",
        type=int, default=1,
        help="Start from this stage (1-7, default: 1)",
    )
    parser.add_argument(
        "--end-stage",
        type=int, default=8,
        help="End at this stage (1-8, default: 8)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write output files",
    )
    parser.add_argument(
        "--max-workers",
        type=int, default=5,
        help="Parallel workers for body translation (default: 5)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model override (default: resolved by factory — mini for translation, nano for cleanup)",
    )
    parser.add_argument(
        "--chapters",
        type=int, default=0,
        help="Limit to first N chapters (0 = all, default: 0)",
    )

    args = parser.parse_args()

    config = OrchestrationConfig(
        start_stage=args.start_stage,
        end_stage=args.end_stage,
        dry_run=args.dry_run,
        max_workers=args.max_workers,
        model=args.model,
        max_concurrent_chapters=args.max_workers,
    )

    pipeline = TranslationPipeline(config)
    result = pipeline.run(
        work_number=args.work_number,
        volume=args.volume,
        resume=args.resume,
        chapter_limit=args.chapters,
    )

    # Print summary
    print(f"\n{'='*60}")
    print(f"PIPELINE RESULT")
    print(f"{'='*60}")
    print(f"Work: {result['work_number']}")
    print(f"Success: {result['success']}")
    print(f"Duration: {result['duration_seconds']/60:.1f} minutes")
    print(f"Unique terms tracked: {result['accumulator_terms']}")

    for stage in result["stages"]:
        status = "OK" if stage["success"] else "FAILED"
        print(f"  Stage {stage['stage']} ({stage['name']}): {status}")
        if not stage["success"]:
            print(f"    Error: {stage.get('error', 'unknown')}")

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
