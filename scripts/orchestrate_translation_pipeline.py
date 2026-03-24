#!/usr/bin/env python3
"""
Translation Pipeline Orchestrator

8-stage translation pipeline with cultural footnotes, cleanup, and EPUB generation:
- Stage 1 (BODY): Prompts + FootnoteContextAccumulator + suppress list
- Stage 2 (METADATA): Title/author translation (no footnotes)
- Stage 3 (TOC): Table of contents translation (no footnotes)
- Stage 4 (HEADINGS): Chapter heading translation (no footnotes)
- Stage 5 (SPECIAL): Front/back matter translation
- Stage 6 (CLEANUP): 6a (character removal) + 6b (triviality) + 6c (density diagnostic) + 6d (verbose trimming)
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
from tqdm import tqdm

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

    def backup_wip(self, filename: str, stage: PipelineStage, tag: str = "") -> Optional[Path]:
        """Create a timestamped backup of an existing WIP file before overwriting."""
        wip_path = self._wip_path(filename, stage)
        if not wip_path.exists():
            return None
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{tag}" if tag else ""
        backup_path = wip_path.with_name(f"{wip_path.stem}_backup_{ts}{suffix}.json")
        import shutil
        shutil.copy2(wip_path, backup_path)
        logger.info(f"Backed up WIP: {backup_path}")
        return backup_path

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
# HONORIFIC PROCESSING (6e italicization + 6f footnote injection)
# =============================================================================

# Honorific registry: pinyin → (ideogram, explanation for footnote)
_HONORIFIC_REGISTRY = {
    # Martial/Jianghu
    "Shīxiōng": ("師兄", "Senior fellow disciple — a martial-arts brother who entered training under the same master earlier."),
    "Shīdì": ("師弟", "Junior fellow disciple — a martial-arts brother who entered training under the same master later."),
    "Shījiě": ("師姐", "Senior female fellow disciple under the same master."),
    "Shīmèi": ("師妹", "Junior female fellow disciple under the same master."),
    "Shīfù": ("師父", "One's own martial-arts master or teacher."),
    "Shīshū": ("師叔", "Martial uncle — one's master's junior martial brother."),
    "Shībó": ("師伯", "Martial uncle — one's master's senior martial brother."),
    "Qiánbèi": ("前輩", "A respectful address for a senior or elder in the martial-arts world."),
    "Wǎnbèi": ("晚輩", "A self-deprecating term meaning 'junior', used when addressing a martial-arts senior."),
    "Shàoxiá": ("少俠", "Young hero — a respectful address for a promising young martial artist."),
    "Dàxiá": ("大俠", "Great hero — an honorific for a renowned, righteous martial artist."),
    "Nǚxiá": ("女俠", "Heroine or swordswoman — the female equivalent of a great hero."),
    "Zhǎngmén": ("掌門", "Sect leader — the head of a martial-arts school or sect."),
    "Méngzhǔ": ("盟主", "Alliance chief — the elected leader of a confederation of martial-arts sects."),
    "Jiàozhǔ": ("教主", "Cult or sect master — the supreme leader of a religious or heterodox sect."),
    "Bāngzhǔ": ("幫主", "Gang chief — the leader of a martial-arts gang or brotherhood."),
    "Zhàizhǔ": ("寨主", "Stronghold chief — the leader of a mountain stronghold or bandit lair."),
    "Zhuāngzhǔ": ("莊主", "Manor lord — the master of a martial-arts manor or estate."),
    "Tángzhǔ": ("堂主", "Hall master — a sub-leader within a sect, heading one of its divisions."),
    "Hùfǎ": ("護法", "Dharma protector — a guardian elder or enforcer within a sect."),
    "Zhǎnglǎo": ("長老", "Elder — a senior rank within a martial-arts sect."),
    # Family/Social
    "Dàgē": ("大哥", "Elder brother — a familiar or sworn-brotherhood address."),
    "Dàsǎo": ("大嫂", "Elder brother's wife or sister-in-law."),
    "Sǎozi": ("嫂子", "Sister-in-law — an informal address for an elder brother's wife."),
    "Bófù": ("伯父", "Uncle — specifically one's father's elder brother."),
    "Bómǔ": ("伯母", "Aunt — specifically one's father's elder brother's wife."),
    "Shūshu": ("叔叔", "Uncle — specifically one's father's younger brother."),
    "Yímā": ("姨媽", "Aunt — specifically one's mother's sister."),
    "Gūniáng": ("姑娘", "Miss — a respectful address for a young unmarried woman."),
    "Xiǎojiě": ("小姐", "Miss — a more formal address for a young woman, often with surname."),
    "Gōngzǐ": ("公子", "Young master or young lord — the son of a noble or wealthy family."),
    "Shàoyé": ("少爺", "Young master — the young heir of a household."),
    "Fūrén": ("夫人", "Madam or Lady — a respectful address for a married woman of status."),
    "Tàitai": ("太太", "Madam or wife — a general address for a married woman."),
    "Lǎo Tàitai": ("老太太", "Old madam — a respectful address for an elderly matriarch."),
    "Lǎoyé": ("老爺", "My lord or your lordship — an address for an official or master of a household."),
    "Yātou": ("丫頭", "Maidservant or girl — a familiar, sometimes affectionate address."),
    # Imperial/Official
    "Wángyé": ("王爺", "Prince or royal lord — a member of the imperial family holding a princely title."),
    "Tàizǐ": ("太子", "Crown prince — the designated heir to the imperial throne."),
    "Jiāngjūn": ("將軍", "General — a high-ranking military commander."),
    "Dàrén": ("大人", "Lord or your excellency — a respectful address for a government official."),
    "Shèngshàng": ("聖上", "His Majesty — a reverent address for the reigning emperor."),
    # Religious
    "Dàshī": ("大師", "Great master — a Buddhist honorific for a highly respected monk."),
    "Fāngzhàng": ("方丈", "Abbot — the head of a Buddhist monastery."),
    "Zhùchí": ("住持", "Abbot — an alternate title for the head of a Buddhist monastery."),
    "Dàozhǎng": ("道長", "Taoist master — a respectful address for a senior Taoist priest."),
    "Zhēnrén": ("真人", "Perfected one — a Taoist honorific for one who has attained spiritual mastery."),
}

_HONORIFIC_PINYIN = list(_HONORIFIC_REGISTRY.keys())

# Build compiled regex: match honorific pinyin NOT already wrapped in *...*
_HONORIFIC_RE = None


def _build_honorific_regex():
    """Build compiled regex for all honorific pinyin forms."""
    global _HONORIFIC_RE
    forms = sorted(_HONORIFIC_PINYIN, key=len, reverse=True)
    escaped = [re.escape(f) for f in forms]
    pattern = r"(?<!\*)(" + "|".join(escaped) + r")(?!\*)"
    _HONORIFIC_RE = re.compile(pattern)


# Also build a regex that matches both bare and italicized forms
_HONORIFIC_ANY_RE = None


def _build_honorific_any_regex():
    """Build regex matching honorific pinyin whether or not italicized."""
    global _HONORIFIC_ANY_RE
    forms = sorted(_HONORIFIC_PINYIN, key=len, reverse=True)
    escaped = [re.escape(f) for f in forms]
    # Match with or without surrounding asterisks
    pattern = r"\*?(" + "|".join(escaped) + r")\*?"
    _HONORIFIC_ANY_RE = re.compile(pattern)


def _italicize_honorifics(data: Dict[str, Any]) -> int:
    """Wrap bare honorific pinyin in *asterisks* for italic rendering.

    Returns number of honorific occurrences italicized.
    """
    if _HONORIFIC_RE is None:
        _build_honorific_regex()

    count = 0
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            text = block.get("translated_content", "")
            if not text:
                continue
            new_text, n = _HONORIFIC_RE.subn(r"*\1*", text)
            if n > 0:
                block["translated_content"] = new_text
                count += n
    return count


def _ensure_honorific_footnotes(data: Dict[str, Any]) -> int:
    """Ensure every honorific has a footnote on its first occurrence.

    Scans all chapters in order. For each honorific pinyin form found,
    checks whether a footnote already exists (in that block or any prior
    block). If not, injects a footnote on the first occurrence.

    Returns number of footnotes injected.
    """
    if _HONORIFIC_ANY_RE is None:
        _build_honorific_any_regex()

    seen_honorifics: set = set()  # pinyin forms already footnoted
    injected = 0

    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    # First pass: collect which honorifics already have footnotes anywhere
    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            for fn in block.get("footnotes", []):
                ideogram = fn.get("ideogram", "")
                # Check if this footnote's ideogram matches a known honorific
                for pinyin, (ideo, _) in _HONORIFIC_REGISTRY.items():
                    if ideogram == ideo:
                        seen_honorifics.add(pinyin)

    # Second pass: find first occurrence of each missing honorific, inject footnote
    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            text = block.get("translated_content", "")
            if not text:
                continue

            # Find all honorific matches in this block
            for match in _HONORIFIC_ANY_RE.finditer(text):
                pinyin = match.group(1)
                if pinyin in seen_honorifics:
                    continue
                if pinyin not in _HONORIFIC_REGISTRY:
                    continue

                # This honorific needs a footnote — inject it
                seen_honorifics.add(pinyin)
                ideogram, explanation = _HONORIFIC_REGISTRY[pinyin]

                fns = block.get("footnotes", [])
                # Determine next footnote key for this block
                existing_keys = [fn.get("key", 0) for fn in fns]
                next_key = max(existing_keys, default=0) + 1

                # Add footnote entry
                fns.append({
                    "key": next_key,
                    "ideogram": ideogram,
                    "pinyin": pinyin.lower(),
                    "explanation": explanation,
                })
                block["footnotes"] = fns

                # Insert [N] marker after the first occurrence in the text
                marker = f"[{next_key}]"
                pos = match.end()
                block["translated_content"] = text[:pos] + marker + text[pos:]
                # Update text for subsequent matches in this block
                text = block["translated_content"]

                injected += 1

    return injected


# Tone mark characters used to detect pinyin words
_TONE_CHARS = set("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜĀÁǍÀĒÉĚÈĪÍǏÌŌÓǑÒŪÚǓÙǕǗǙǛ")

# Regex: a "word" containing at least one tone diacritic, possibly with
# punctuation attached (commas, periods, parens, quotes, dashes).
# We capture: optional leading punct + pinyin-word + optional trailing punct
_PINYIN_WORD_RE = re.compile(
    r'(?<!\*)'                  # not already preceded by *
    r'([(\["\']*'               # optional leading punct/quotes
    r'[A-Za-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜĀÁǍÀĒÉĚÈĪÍǏÌŌÓǑÒŪÚǓÙǕǗǙǛ]+'  # the word
    r'[)\]"\',;.!?:—]*'        # optional trailing punct
    r')'
    r'(?!\*)'                   # not already followed by *
)


def _has_tone(word: str) -> bool:
    """Check if a word contains pinyin tone diacritics."""
    return any(c in _TONE_CHARS for c in word)


def _italicize_pinyin_in_text(text: str) -> tuple[str, int]:
    """Wrap bare pinyin words (containing tone marks) in *asterisks*.

    Groups consecutive pinyin words into a single italic span:
    "Wú Sānguì" → "*Wú Sānguì*" (not "*Wú* *Sānguì*")

    Returns (new_text, count_of_spans_italicized).
    """
    if not text:
        return text, 0

    words = text.split(" ")
    result = []
    count = 0
    i = 0

    while i < len(words):
        word = words[i]
        # Strip surrounding asterisks to check if already italic
        stripped = word.strip("*")

        if _has_tone(stripped) and not (word.startswith("*") and word.endswith("*")):
            # Start of a pinyin span — collect consecutive pinyin words
            span = [word]
            j = i + 1
            while j < len(words):
                next_stripped = words[j].strip("*")
                if _has_tone(next_stripped) and not (words[j].startswith("*") and words[j].endswith("*")):
                    span.append(words[j])
                    j += 1
                else:
                    break

            # Wrap the span in italics
            span_text = " ".join(span)
            # Strip leading/trailing punctuation outside the asterisks
            # e.g. "(Sānguì," → "(*Sānguì*,"
            leading = ""
            inner = span_text
            # Pull off leading punctuation
            while inner and inner[0] in "([\"'":
                leading += inner[0]
                inner = inner[1:]
            # Pull off trailing punctuation
            trailing = ""
            while inner and inner[-1] in ",.;:!?—)]\"\' ":
                trailing = inner[-1] + trailing
                inner = inner[:-1]
            result.append(f"{leading}*{inner}*{trailing}")
            count += 1
            i = j
        else:
            result.append(word)
            i += 1

    return " ".join(result), count


def _italicize_pinyin_in_footnotes(data: Dict[str, Any]) -> int:
    """Italicize bare pinyin words in footnote explanations.

    Returns number of footnotes modified.
    """
    modified = 0
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            for fn in block.get("footnotes", []):
                expl = fn.get("explanation", "")
                if not expl:
                    continue
                new_expl, n = _italicize_pinyin_in_text(expl)
                if n > 0:
                    fn["explanation"] = new_expl
                    modified += 1
    return modified


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

        # 6d: Trim verbose footnote explanations
        logger.info("  6d: Trimming verbose footnotes...")
        try:
            trimmed_6d = self._trim_verbose_footnotes(data)
            if trimmed_6d:
                logger.info(f"    6d trimmed {trimmed_6d} verbose footnotes")
            else:
                logger.info("    6d: no verbose footnotes found")
        except Exception as e:
            logger.error(f"    6d failed: {e}")
            errors.append(f"6d: {e}")

        # 6e: Enforce italicized honorific pinyin
        logger.info("  6e: Italicizing honorific pinyin...")
        italicized_count = _italicize_honorifics(data)
        if italicized_count:
            logger.info(f"    6e italicized {italicized_count} honorific occurrences")
        else:
            logger.info("    6e: all honorifics already italicized")

        # 6f: Ensure honorific footnotes on first occurrence
        logger.info("  6f: Ensuring honorific footnotes...")
        injected_count = _ensure_honorific_footnotes(data)
        if injected_count:
            logger.info(f"    6f injected {injected_count} missing honorific footnotes")
        else:
            logger.info("    6f: all honorifics already footnoted")

        # 6g: Italicize pinyin in footnote explanations
        logger.info("  6g: Italicizing pinyin in footnotes...")
        fn_italicized = _italicize_pinyin_in_footnotes(data)
        if fn_italicized:
            logger.info(f"    6g italicized pinyin in {fn_italicized} footnotes")
        else:
            logger.info("    6g: all footnote pinyin already italicized")

        # 6h: Consistency checks — dramatis personae, pinyin, gender, tense
        logger.info("  6h: Consistency checks...")
        try:
            consistency_report = self._run_consistency_checks(data)
            if consistency_report:
                dp_count = len(consistency_report.get("dramatis_personae", []))
                pinyin_issues = len(consistency_report.get("pinyin_variants", []))
                gender_issues = len(consistency_report.get("gender_mismatches", []))
                mixed_tense = len(consistency_report.get("mixed_tense_blocks", []))
                logger.info(
                    f"    6h: {dp_count} characters, "
                    f"{pinyin_issues} pinyin variants, "
                    f"{gender_issues} gender flags, "
                    f"{mixed_tense} mixed-tense blocks"
                )
                # Stash report in data for validation stage
                data.setdefault("_pipeline_reports", {})["consistency"] = consistency_report
        except Exception as e:
            logger.error(f"    6h failed: {e}")
            errors.append(f"6h: {e}")

        # 6i: Retranslate mixed-tense blocks with preceding context
        logger.info("  6i: Retranslating mixed-tense blocks...")
        try:
            retranslated_6i = self._retranslate_mixed_tense(data)
            if retranslated_6i:
                logger.info(f"    6i retranslated {retranslated_6i} mixed-tense blocks")
            else:
                logger.info("    6i: no mixed-tense blocks to retranslate")
        except Exception as e:
            logger.error(f"    6i failed: {e}")
            errors.append(f"6i: {e}")

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

    def _trim_verbose_footnotes(
        self, data: Dict[str, Any], batch_size: int = 20
    ) -> int:
        """
        6d: Remove story context from footnote explanations.

        Sends ALL footnotes to the AI to strip narrative interpretation,
        editorial commentary, and scene-specific context. Keeps only
        factual cultural/historical content.

        Returns number of footnotes rewritten.
        """
        from openai import OpenAI

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        # Collect all footnotes (mutable refs so we can edit in place)
        all_fns: list[dict] = []
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                for fn in block.get("footnotes", []):
                    if fn.get("explanation", "").strip():
                        all_fns.append(fn)

        if not all_fns:
            return 0

        logger.info(f"    Reviewing {len(all_fns)} footnotes for story context...")

        client = OpenAI()
        trimmed = 0

        system_prompt = (
            "You are editing footnotes in a translated Chinese novel. "
            "Each footnote should state ONLY what the term IS — its factual "
            "definition, historical identity, or cultural significance.\n\n"
            "STRIP these patterns from every footnote:\n"
            "- Story interpretation: 'underscoring the gravity', 'indicating "
            "the importance of', 'reflecting the character's...'\n"
            "- Scene narration: 'in this scene', 'here it refers to', "
            "'the presence of X indicates...'\n"
            "- Editorial commentary: 'often hampered by', 'a grave gesture', "
            "'pivotal to the plot'\n"
            "- Redundant elaboration that restates the definition in different words\n\n"
            "KEEP: historical facts, dynasty names, dates, official functions, "
            "cultural practices, religious/philosophical context.\n\n"
            "If a footnote is already clean and factual, return it unchanged.\n\n"
            'Return ONLY a JSON object: {"trimmed": [\n'
            '  {"ideogram": "<chinese_chars>", "explanation": "<cleaned_text>"},\n'
            "  ...\n"
            "]}\n"
            "CRITICAL: Include the EXACT ideogram from the input so results "
            "can be matched. Same count as input."
        )

        # Build ideogram→fn lookup for safe matching
        ideo_to_fns: dict[str, list[dict]] = {}
        for fn in all_fns:
            ideo = fn.get("ideogram", "").strip()
            if ideo:
                ideo_to_fns.setdefault(ideo, []).append(fn)

        for i in tqdm(range(0, len(all_fns), batch_size),
                       desc="Trimming footnotes", total=(len(all_fns) + batch_size - 1) // batch_size):
            batch = all_fns[i:i + batch_size]
            user_lines = []
            for idx, fn in enumerate(batch, 1):
                ideo = fn.get("ideogram", "")
                expl = fn.get("explanation", "")
                user_lines.append(f"{idx}. {ideo} — {expl}")

            try:
                resp = client.chat.completions.create(
                    model="gpt-4.1-nano",
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "\n".join(user_lines)},
                    ],
                )
                result_text = resp.choices[0].message.content.strip()
                result_data = json.loads(result_text)

                # Extract trimmed results — expect list of {ideogram, explanation}
                trimmed_list = None
                if isinstance(result_data, dict):
                    for key in ("trimmed", "results", "explanations", "footnotes"):
                        if key in result_data and isinstance(result_data[key], list):
                            trimmed_list = result_data[key]
                            break
                    if trimmed_list is None:
                        for v in result_data.values():
                            if isinstance(v, list) and len(v) > 0:
                                trimmed_list = v
                                break

                if not trimmed_list:
                    continue

                # Match by ideogram (safe) rather than position (fragile)
                batch_ideo_map = {fn.get("ideogram", "").strip(): fn for fn in batch}
                for item in trimmed_list:
                    if isinstance(item, dict):
                        ideo = item.get("ideogram", "").strip()
                        new_expl = item.get("explanation", "").strip()
                    elif isinstance(item, str):
                        # Fallback: positional match if model returns flat strings
                        # Only safe if count matches exactly
                        continue
                    else:
                        continue

                    if not ideo or not new_expl:
                        continue

                    fn = batch_ideo_map.get(ideo)
                    if fn and new_expl != fn["explanation"]:
                        fn["explanation"] = new_expl
                        trimmed += 1

            except Exception as e:
                logger.warning(f"    6d batch {i // batch_size + 1} failed: {e}")
                continue

        return trimmed

    # -----------------------------------------------------------------
    # 6h: Consistency checks — dramatis personae + pinyin + gender + tense
    # -----------------------------------------------------------------

    def _run_consistency_checks(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        6h: Build a dramatis personae via light AI call, then run
        programmatic consistency scanners for pinyin, gender, and tense.

        Returns a report dict with findings.
        """
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        if not chapters:
            return {}

        # Step 1: Build dramatis personae (light AI)
        dramatis = self._build_dramatis_personae(data)
        data["_dramatis_personae"] = dramatis

        # Step 2: Pinyin consistency scan
        pinyin_variants = self._check_pinyin_consistency(chapters, dramatis)

        # Step 3: Gender pronoun spot-check
        gender_mismatches = self._check_gender_consistency(chapters, dramatis)

        # Step 4: Tense scan — tag each block
        mixed_tense_blocks = self._scan_tense(chapters)

        return {
            "dramatis_personae": dramatis,
            "pinyin_variants": pinyin_variants,
            "gender_mismatches": gender_mismatches,
            "mixed_tense_blocks": mixed_tense_blocks,
        }

    # Known honorific/title tokens to exclude from name extraction
    _HONORIFIC_TOKENS = {
        "shīxiōng", "shīdì", "shījiě", "shīmèi", "shīfù", "shīshū",
        "shībó", "qiánbèi", "wǎnbèi", "shàoxiá", "dàxiá", "nǚxiá",
        "zhǎngmén", "méngzhǔ", "jiàozhǔ", "bāngzhǔ", "zhàizhǔ",
        "zhuāngzhǔ", "tángzhǔ", "hùfǎ", "zhǎnglǎo", "dàgē", "dàsǎo",
        "sǎozi", "bófù", "bómǔ", "shūshu", "yímā", "gūniáng", "xiǎojiě",
        "gōngzǐ", "shàoyé", "fūrén", "tàitai", "lǎoyé", "yātou",
        "wángyé", "tàizǐ", "jiāngjūn", "dàrén", "shèngshàng",
        "dàshī", "fāngzhàng", "zhùchí", "dàozhǎng", "zhēnrén",
        "gōnggong", "xiānggōng", "guǎnjiā", "shàozhàizhǔ",
        "jūshì", "lángzhōng", "xiānshēng", "dàyuánshuài",
        # Additional titles/honorifics that leaked through in testing
        "dàyé", "bóbó", "fó", "miàn", "cáizhǔ", "bānzhǔ",
        "shīgē", "shìxiōng",
    }

    def _build_dramatis_personae(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract proper names from translated text and footnotes, then use a
        light AI call to cluster them into characters with canonical spelling,
        gender, and aliases.
        """
        from openai import OpenAI

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        # Collect all pinyin proper names (capitalized words with tone diacritics)
        tone_chars = set("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ")
        name_counts: Dict[str, int] = {}

        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                text = block.get("translated_content", "")
                # Find capitalized words with tone marks
                tokens = re.findall(r"[A-ZÀ-Ý\u0100-\u01FF][a-zà-ÿ\u0100-\u01FF'ʼ]+", text)
                for token in tokens:
                    # Strip possessive 's before counting
                    clean = re.sub(r"['ʼ]s$", "", token)
                    if not clean:
                        continue
                    if any(c in tone_chars for c in clean):
                        name_counts[clean] = name_counts.get(clean, 0) + 1

        # Filter out known honorifics and single-syllable tokens (likely fragments)
        filtered_names: Dict[str, int] = {}
        for name, count in name_counts.items():
            if name.lower() in self._HONORIFIC_TOKENS:
                continue
            # Skip very short tokens (single syllable like "Hú", "Lǐ") unless
            # they appear 5+ times — these are likely surnames used alone
            if len(name) <= 3 and count < 5:
                continue
            if count >= 2:
                filtered_names[name] = count

        # Also collect names from footnotes
        footnote_names = []
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                for fn in block.get("footnotes", []):
                    ideogram = fn.get("ideogram", "")
                    explanation = fn.get("explanation", "")
                    if ideogram and explanation:
                        footnote_names.append(f"{ideogram}: {explanation}")

        if not filtered_names:
            return []

        # Light AI call to cluster names into characters
        client = OpenAI()
        # Sort by frequency descending so the model sees important names first
        sorted_names = sorted(filtered_names.items(), key=lambda x: -x[1])
        name_list = ", ".join(f"{n} ({c}x)" for n, c in sorted_names[:150])
        fn_context = "\n".join(footnote_names[:80])

        prompt = (
            "Below are pinyin names extracted from a translated Chinese wuxia novel "
            "(with occurrence counts), plus footnote context.\n\n"
            "YOUR TASK: Group these into individual CHARACTERS (people in the story). "
            "Cluster different spellings and name forms that refer to the same person.\n\n"
            "CRITICAL RULES:\n"
            "- Each entry = ONE person. Do NOT merge two different characters.\n"
            "- Chinese names have SURNAME + GIVEN NAME. 'Cáo Yúnqí' and 'Miáo Ruòlán' "
            "are DIFFERENT people (different surnames: Cáo vs Miáo). Do NOT merge them.\n"
            "- A given name alone (e.g. 'Ruòlán') is an alias for the full name "
            "(e.g. 'Miáo Ruòlán'), NOT a separate character.\n"
            "- A surname alone (e.g. 'Miáo') used 50x is likely the same person "
            "referred to by surname only.\n"
            "- EXCLUDE place names (mountains, cities, provinces, lakes, regions)\n"
            "- EXCLUDE honorific/title words (Shīxiōng, Gūniáng, Dàshī, Gōnggong, "
            "Xiānggōng, Dàyé, Wángyé, etc.)\n"
            "- EXCLUDE common nouns, martial arts terms, religious terms (Fó, Chán)\n"
            "- INCLUDE only actual fictional or historical PEOPLE\n\n"
            "GENDER RULES:\n"
            "- Only mark 'female' if you have STRONG evidence: 姑娘/小姐/夫人/三娘/嫂 "
            "in the name or footnotes, or the character is a well-known female figure.\n"
            "- Only mark 'male' if you have strong evidence: 公子/少爺/大俠 markers, "
            "or the character is a well-known male figure.\n"
            "- When in doubt, say 'unknown'. Wrong gender is worse than unknown.\n\n"
            "ALIASES:\n"
            "- List spelling variants from the name list that refer to this person "
            "(e.g. different romanizations, surname-only, given-name-only).\n"
            "- Do NOT put different people's names as aliases of each other.\n\n"
            "Names: " + name_list + "\n\n"
            "Footnote context:\n" + fn_context + "\n\n"
            'Return JSON: {"characters": [{"canonical": "Surname Givenname", '
            '"ideogram": "漢字", "gender": "male|female|unknown", '
            '"aliases": ["Givenname", "Surname"]}, ...]}\n'
        )

        try:
            resp = client.chat.completions.create(
                model="gpt-4.1-mini",
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            result = json.loads(resp.choices[0].message.content.strip())
            characters = result.get("characters", [])
            logger.info(f"    Dramatis personae: {len(characters)} characters identified")
            return characters
        except Exception as e:
            logger.warning(f"    Dramatis personae AI call failed: {e}")
            return []

    def _check_pinyin_consistency(
        self, chapters: List[Dict], dramatis: List[Dict]
    ) -> List[Dict[str, Any]]:
        """
        Check that each character's name is spelled consistently throughout.
        Uses the dramatis personae aliases to detect variants.
        Also does a second pass: scan all blocks for pinyin tokens and group
        by stripped-diacritic form to catch variants the AI missed.
        """
        issues = []

        # Pass 1: Check dramatis personae aliases
        for char in dramatis:
            canonical = char.get("canonical", "")
            aliases = [a for a in char.get("aliases", []) if a != canonical]
            # Normalize: strip possessives from aliases
            clean_aliases = list({re.sub(r"['ʼ]s$", "", a) for a in aliases} - {canonical})
            if clean_aliases:
                issues.append({
                    "character": canonical,
                    "variants": clean_aliases,
                    "recommendation": f"Standardize to '{canonical}' throughout",
                })

        # Pass 2: Scan all blocks for pinyin variants by base form
        import unicodedata
        tone_chars = set("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ")

        def strip_diacritics(s: str) -> str:
            nfkd = unicodedata.normalize("NFKD", s)
            return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()

        pinyin_groups: Dict[str, Dict[str, int]] = {}  # base → {variant: count}
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                text = block.get("translated_content", "")
                tokens = re.findall(
                    r"[A-ZÀ-Ý\u0100-\u01FF][a-zà-ÿ\u0100-\u01FF'ʼ]+", text
                )
                for token in tokens:
                    clean = re.sub(r"['ʼ]s$", "", token)
                    if not any(c in tone_chars for c in clean):
                        continue
                    if clean.lower() in self._HONORIFIC_TOKENS:
                        continue
                    base = strip_diacritics(clean)
                    pinyin_groups.setdefault(base, {})
                    pinyin_groups[base][clean] = pinyin_groups[base].get(clean, 0) + 1

        # Flag groups with multiple surface forms (true pinyin inconsistency)
        already_reported = {i["character"] for i in issues}
        for base, variants in pinyin_groups.items():
            if len(variants) <= 1:
                continue
            # Pick the most frequent as canonical
            sorted_v = sorted(variants.items(), key=lambda x: -x[1])
            canonical_v = sorted_v[0][0]
            if canonical_v in already_reported:
                continue
            other_forms = [v for v, _ in sorted_v[1:]]
            issues.append({
                "character": canonical_v,
                "variants": other_forms,
                "counts": dict(sorted_v),
                "recommendation": f"Standardize to '{canonical_v}' throughout",
            })

        return issues

    def _check_gender_consistency(
        self, chapters: List[Dict], dramatis: List[Dict]
    ) -> List[Dict[str, Any]]:
        """
        For each block, cross-reference pronoun usage against source 她/他.
        Flag blocks where source has 她 but translation has no she/her,
        or where a known female character is referred to with he/him.
        """
        # Build set of known female character names — only use
        # multi-syllable names (8+ chars) to avoid false positives from
        # short surnames or fragments. Require canonical to be a plausible
        # full name (contains a space or apostrophe, or 6+ chars).
        female_names = set()
        unknown_names = set()  # For 她-based fallback check
        for char in dramatis:
            canonical = char.get("canonical", "")
            is_full_name = (
                " " in canonical or "'" in canonical or len(canonical) >= 6
            )
            if char.get("gender") == "female":
                if is_full_name:
                    female_names.add(canonical.lower())
                for alias in char.get("aliases", []):
                    if len(alias) >= 6:
                        female_names.add(alias.lower())
            elif char.get("gender") == "unknown":
                if is_full_name:
                    unknown_names.add(canonical.lower())
                for alias in char.get("aliases", []):
                    if len(alias) >= 6:
                        unknown_names.add(alias.lower())

        issues = []
        for ch_idx, chapter in enumerate(chapters):
            for blk_idx, block in enumerate(chapters[ch_idx].get("content_blocks", [])):
                source = block.get("content", "")
                translated = block.get("translated_content", "")
                if not source or not translated:
                    continue

                # Count gendered pronouns in source
                she_count_source = source.count("她")
                he_count_source = source.count("他")

                # Count in translation (outside quotes for accuracy)
                trans_lower = translated.lower()
                she_count_trans = (
                    trans_lower.count(" she ")
                    + trans_lower.count(" her ")
                    + trans_lower.count(" hers ")
                )
                he_count_trans = (
                    trans_lower.count(" he ")
                    + trans_lower.count(" him ")
                    + trans_lower.count(" his ")
                )

                # Flag: source has 2+ 她 but translation has zero she/her
                # (single 她 can legitimately map to a different sentence or
                # be inside quoted speech referring to someone else)
                if she_count_source >= 2 and she_count_trans == 0:
                    issues.append({
                        "chapter": ch_idx,
                        "block": blk_idx,
                        "block_id": block.get("id", ""),
                        "issue": f"Source has {she_count_source}x 她 but "
                                 f"translation has 0 she/her",
                        "severity": "warning",
                    })

                # Flag: source has 1+ 她 AND an unknown-gender character name
                # appears in the translation with "he/him" — likely a gender
                # error the dramatis personae couldn't catch due to unknown gender
                elif she_count_source >= 1 and she_count_trans == 0 and unknown_names:
                    trans_lower = translated.lower()
                    matched_unknown = [
                        name for name in unknown_names
                        if name and name in trans_lower
                    ]
                    if matched_unknown and he_count_trans > 0:
                        issues.append({
                            "chapter": ch_idx,
                            "block": blk_idx,
                            "block_id": block.get("id", ""),
                            "issue": f"Source has {she_count_source}x 她, "
                                     f"unknown-gender '{matched_unknown[0]}' "
                                     f"present with he/him but no she/her",
                            "severity": "info",
                        })

                # Flag: known female character name + "he/him" in same
                # sentence with NO "she/her" anywhere in that sentence.
                # Only flag full-name matches (2+ syllable) to avoid
                # false positives from single-syllable surname matches.
                if female_names:
                    # Strip quoted speech — pronouns inside quotes may
                    # refer to characters the speaker is discussing
                    narration = re.sub(r'"[^"]*"', '', translated)
                    narration = re.sub(r'\u201c[^\u201d]*\u201d', '', narration)
                    sentences = re.split(r'[.!?]', narration)
                    for sent in sentences:
                        sent_lower = sent.lower()
                        # Only match names with 2+ syllables (5+ chars)
                        has_female_name = any(
                            name in sent_lower
                            for name in female_names
                            if name and len(name) >= 5
                        )
                        has_he = " he " in sent_lower or " him " in sent_lower
                        has_she = " she " in sent_lower or " her " in sent_lower
                        if has_female_name and has_he and not has_she:
                            issues.append({
                                "chapter": ch_idx,
                                "block": blk_idx,
                                "block_id": block.get("id", ""),
                                "issue": f"Female character + 'he/him' without "
                                         f"'she/her' in sentence",
                                "severity": "warning",
                                "snippet": sent.strip()[:100],
                            })
        return issues

    def _scan_tense(self, chapters: List[Dict]) -> List[Dict[str, Any]]:
        """
        Scan each translated block for tense consistency.
        Tags each block with detected_tense: "past", "present", or "mixed".
        Returns list of mixed-tense blocks for 6i retranslation.
        """
        # Narrative past-tense verbs (irregular forms that are unambiguous)
        past_markers = re.compile(
            r'\b(said|went|came|stood|drew|struck|turned|looked|asked|replied|'
            r'answered|walked|ran|fell|thought|knew|saw|heard|felt|took|gave|'
            r'held|pulled|pushed|threw|caught|brought|fought|leaped|laughed|'
            r'cried|whispered|shouted|nodded|shook|bowed|raised|lowered|'
            r'stepped|moved|grabbed|slashed|pierced|dodged|landed|'
            r'retreated|advanced|rushed|charged|appeared|vanished|continued|'
            r'exclaimed|murmured|muttered|sighed|gasped|groaned|snorted|'
            r'was|were|had|did|could|would)\b'
        )
        # Present-tense verbs (third-person singular narrative forms)
        present_markers = re.compile(
            r'\b(says|goes|comes|stands|draws|strikes|turns|looks|asks|replies|'
            r'answers|walks|runs|falls|thinks|knows|sees|hears|feels|takes|gives|'
            r'holds|pulls|pushes|throws|catches|brings|fights|leaps|laughs|'
            r'cries|whispers|shouts|nods|shakes|bows|raises|lowers|'
            r'steps|moves|grabs|slashes|pierces|dodges|lands|'
            r'retreats|advances|rushes|charges|appears|vanishes|continues|'
            r'exclaims|murmurs|mutters|sighs|gasps|groans|snorts)\b'
        )
        # Ambiguous words that can be nouns, adjectives, or present tense —
        # exclude from counting to reduce false positives
        # (is/are/has/does/can/will/blocks removed — too ambiguous)

        mixed_blocks = []

        for ch_idx, chapter in enumerate(chapters):
            for blk_idx, block in enumerate(chapter.get("content_blocks", [])):
                translated = block.get("translated_content", "")
                if not translated or len(translated) < 80:
                    block["detected_tense"] = "short"
                    continue

                # Strip ALL quoted speech (straight and curly quotes)
                narration = re.sub(r'"[^"]*"', '', translated)
                narration = re.sub(r'\u201c[^\u201d]*\u201d', '', narration)
                # Also strip single-quoted speech
                narration = re.sub(r"\u2018[^\u2019]*\u2019", '', narration)
                narration = re.sub(r"'[^']*'", '', narration)

                past_count = len(past_markers.findall(narration))
                present_count = len(present_markers.findall(narration))
                total = past_count + present_count

                # Need at least 5 verb signals to make a judgment
                if total < 5:
                    block["detected_tense"] = "insufficient"
                    continue

                past_ratio = past_count / total
                present_ratio = present_count / total

                if past_ratio >= 0.85:
                    block["detected_tense"] = "past"
                elif present_ratio >= 0.85:
                    block["detected_tense"] = "present"
                else:
                    block["detected_tense"] = "mixed"
                    mixed_blocks.append({
                        "chapter": ch_idx,
                        "block": blk_idx,
                        "block_id": block.get("id", ""),
                        "past_count": past_count,
                        "present_count": present_count,
                        "ratio": f"{past_ratio:.0%} past / {present_ratio:.0%} present",
                    })

        return mixed_blocks

    # -----------------------------------------------------------------
    # 6i: Retranslate mixed-tense blocks with preceding paragraph context
    # -----------------------------------------------------------------

    def _retranslate_mixed_tense(self, data: Dict[str, Any]) -> int:
        """
        For blocks tagged 'mixed' tense, retranslate with the previous
        block's translation as context so the model can match tense.
        Returns count of retranslated blocks.
        """
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        retranslated = 0

        translator = TranslationService(
            model=self.config.model,
            temperature=self.config.temperature,
            genre=self.config.genre,
            author=self.config.author,
        )

        for chapter in chapters:
            blocks = chapter.get("content_blocks", [])
            for i, block in enumerate(blocks):
                if block.get("detected_tense") != "mixed":
                    continue

                source_text = block.get("content", "")
                if not source_text:
                    continue

                # Get previous block's translation for context
                preceding_context = ""
                if i > 0:
                    prev_translated = blocks[i - 1].get("translated_content", "")
                    if prev_translated:
                        # Last 300 chars to keep prompt short
                        preceding_context = prev_translated[-300:]

                # Build augmented translation request
                context_prefix = ""
                if preceding_context:
                    context_prefix = (
                        "[CONTEXT — preceding paragraph's translation, "
                        "for tense consistency. Match its tense:]\n"
                        f'"{preceding_context}"\n\n'
                        "[NOW TRANSLATE THIS BLOCK:]\n"
                    )

                try:
                    response = translator.translate_from_dict({
                        "content_text_id": block.get("id", 0),
                        "content_source_text": context_prefix + source_text,
                    })
                    annotated = response.get("translated_annotated_content", {})
                    new_text = annotated.get("annotated_content_text", "")
                    new_footnotes = annotated.get("footnotes", [])

                    if new_text:
                        block["translated_content"] = new_text
                        block["footnotes"] = new_footnotes
                        block["detected_tense"] = "retranslated"
                        block["_retranslated_reason"] = "mixed_tense"
                        retranslated += 1
                        logger.info(
                            f"    Retranslated block {block.get('id', '?')} "
                            f"(was mixed tense)"
                        )
                except Exception as e:
                    logger.warning(
                        f"    Failed to retranslate block {block.get('id', '?')}: {e}"
                    )

        return retranslated


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
        chapter_offset: int = 0,
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
                    "SELECT category_english, author_chinese, title_english, author_english "
                    "FROM works WHERE work_number = ?",
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
                    # Inject catalog English titles into meta so Stage 2 uses them
                    if row[2] and not meta.get('title_english'):
                        meta['title_english'] = row[2]
                        logger.info(f"Catalog lookup: title_english='{row[2]}'")
                    if row[3] and not meta.get('author_english'):
                        meta['author_english'] = row[3]
                        logger.info(f"Catalog lookup: author_english='{row[3]}'")
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

        # Slice chapters if requested (offset + limit for chunked runs)
        # For chunked body translation: translate the slice, then merge back
        # into the full chapter list so WIP preserves all translated chapters.
        _all_chapters = None  # Will hold full list if chunking
        if chapter_offset > 0 or chapter_limit > 0:
            chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
            total = len(chapters)
            start = min(chapter_offset, total)
            end = min(start + chapter_limit, total) if chapter_limit > 0 else total
            if start > 0 or end < total:
                logger.info(f"Chapters {start+1}-{end} of {total}")
                _all_chapters = chapters  # Keep reference to full list
                data["structure"]["body"]["chapters"] = chapters[start:end]

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
        # Re-inject catalog English titles (may be lost if loading old WIP)
        if self.config.catalog_path and self.config.catalog_path.exists():
            try:
                import duckdb
                conn = duckdb.connect(str(self.config.catalog_path), read_only=True)
                row = conn.execute(
                    "SELECT title_english, author_english FROM works WHERE work_number = ?",
                    [work_number],
                ).fetchone()
                conn.close()
                if row:
                    if row[0] and not meta.get('title_english'):
                        meta['title_english'] = row[0]
                    if row[1] and not meta.get('author_english'):
                        meta['author_english'] = row[1]
            except Exception:
                pass
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

            # For chunked body translation: snapshot the existing WIP
            # BEFORE the processor overwrites it with just the slice
            _pre_chunk_wip = None
            if stage_num == 1 and _all_chapters is not None:
                _pre_chunk_wip = self.wip_manager.load_wip(
                    filename, PipelineStage.BODY
                )
                if _pre_chunk_wip:
                    self.wip_manager.backup_wip(
                        filename, PipelineStage.BODY,
                        tag=f"before_ch{chapter_offset+1}",
                    )

            try:
                data = processor.process(data, filename)

                # Chunked merge: after body translation (stage 1), merge
                # translated chunk back into the full chapter list
                if stage_num == 1 and _all_chapters is not None:
                    translated_chunk = data["structure"]["body"]["chapters"]
                    start = chapter_offset
                    end = start + len(translated_chunk)

                    if _pre_chunk_wip:
                        # Merge into the pre-existing WIP (not the one the
                        # processor just overwrote with only the slice)
                        merged = _pre_chunk_wip["structure"]["body"]["chapters"]
                        for i, ch in enumerate(translated_chunk):
                            idx = start + i
                            if idx < len(merged):
                                merged[idx] = ch
                            else:
                                merged.append(ch)
                        data["structure"]["body"]["chapters"] = merged
                        data["meta"] = _pre_chunk_wip.get("meta", data.get("meta", {}))
                    else:
                        # First chunk — overlay onto the full (untranslated) list
                        for i, ch in enumerate(translated_chunk):
                            _all_chapters[start + i] = ch
                        data["structure"]["body"]["chapters"] = list(_all_chapters)
                    logger.info(
                        f"Merged chunk (ch {start+1}-{end}) "
                        f"into {len(data['structure']['body']['chapters'])} total chapters"
                    )
                    # Re-save WIP with merged data
                    self.wip_manager.save_wip(
                        data, filename, PipelineStage.BODY, {}
                    )

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
        help="Limit to N chapters (0 = all, default: 0)",
    )
    parser.add_argument(
        "--chapter-offset",
        type=int, default=0,
        help="Skip first N chapters (default: 0). Use with --chapters for chunked runs.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Write full log to this file (in addition to stderr)",
    )

    args = parser.parse_args()

    # Set up file logging if requested, or auto-create one
    log_path = args.log_file
    if not log_path:
        log_dir = Path("/tmp")
        log_path = str(log_dir / f"translation_{args.work_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logging.getLogger().addHandler(file_handler)
    logger.info(f"Logging to: {log_path}")

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
        chapter_offset=args.chapter_offset,
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
