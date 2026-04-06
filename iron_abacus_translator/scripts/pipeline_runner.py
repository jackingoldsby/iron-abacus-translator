#!/usr/bin/env python3
"""
DAG-Driven Pipeline Runner

Replaces orchestrate_translation_pipeline.py with a DAG-driven execution engine.
Walks the pipeline DAG in topological order, supports starting from any node,
auto-resume from DuckDB progress, and emits granular progress events.

Usage (via CLI):
    python -m cli.run_pipeline D60 --provider deepseek --workers 10
    python -m cli.run_pipeline D60 --resume
    python -m cli.run_pipeline D60 --from cleanup_6a
    python -m cli.run_pipeline D60 --status

Usage (programmatic):
    from scripts.pipeline_runner import build_pipeline

    runner = build_pipeline(config, progress_db)
    runner.run("D60")
"""

import hashlib
import json
import logging
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
# Crimson Folio (EPUB builder) lives in a sibling product directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "crimson_folio"))

from utils.progress_db import ProgressDB, ProgressEvent
from workflows.dag_engine import DAGDefinition, NodeStatus
from workflows.translation_pipeline_dag import create_v2_pipeline_dag

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RunnerConfig:
    """Configuration for PipelineRunner."""
    # Paths (loaded from environment config if None)
    source_dir: Path = None
    output_dir: Path = None
    wip_dir: Path = None
    log_dir: Path = None
    catalog_path: Path = None

    # Translation settings (heavy model — deepseek, gpt-4.1, etc.)
    model: Optional[str] = None
    provider: Optional[str] = None
    temperature: float = 0.3
    max_retries: int = 2
    timeout: int = 120

    # Lightweight model for cleanup scoring, marker verification, etc.
    cleanup_model: Optional[str] = None
    cleanup_provider: Optional[str] = None

    # Processing settings
    max_workers: int = 5
    rate_limit_delay: float = 0.5
    dry_run: bool = False

    # Footnote cleanup settings
    footnote_batch_size: int = 25
    preserve_historical: bool = True
    preserve_legendary: bool = True
    preserve_cultural: bool = True

    # Target language (ISO 639-1 code)
    target_lang: str = "en"

    # Cross-volume footnote dedup: manifests from prior volumes
    # Each manifest is a dict with "surviving_ideograms" and "surviving_pinyin"
    prior_volume_manifests: Optional[List[Dict[str, Any]]] = None

    # EPUB options
    include_source: bool = False  # Include Chinese source text in EPUB

    verbose: bool = False

    def __post_init__(self):
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
        for d in [self.output_dir, self.wip_dir, self.log_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def get_node_wip_dir(self, node_id: str) -> Path:
        """Get WIP directory for a DAG node.

        Non-English targets get a language subdirectory to keep
        translations for different languages separate.
        """
        d = self.wip_dir / f"node_{node_id}"
        if self.target_lang != "en":
            d = d / self.target_lang
        d.mkdir(parents=True, exist_ok=True)
        return d


# ---------------------------------------------------------------------------
# Stage Processor Protocol
# ---------------------------------------------------------------------------

class StageProcessor:
    """Base class for DAG node processors."""

    def process(self, data: Dict[str, Any], filename: str,
                context: "RunContext") -> Dict[str, Any]:
        """Process a stage. Must return the (possibly modified) data dict."""
        raise NotImplementedError

    @property
    def stage_id(self) -> str:
        """Override to return the DAG node ID this processor handles."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Run Context (passed to processors for progress emission)
# ---------------------------------------------------------------------------

@dataclass
class RunContext:
    """Shared context for a single pipeline run."""
    run_id: str
    work_id: str
    volume: Optional[str]
    config: RunnerConfig
    db: ProgressDB
    dag: DAGDefinition
    target_lang: str = "en"
    kindle_defer: bool = False  # True during series mode — batch send at end
    skip_kindle: bool = True   # Default off — use --kindle flag to enable

    def emit(self, stage: str, event_type: str, status: str = "running",
             chapter_num: int = None, block_id: str = None,
             metadata: Dict[str, Any] = None):
        """Convenience method to emit a progress event."""
        self.db.emit(ProgressEvent(
            run_id=self.run_id,
            work_id=self.work_id,
            stage=stage,
            event_type=event_type,
            status=status,
            volume=self.volume,
            chapter_num=chapter_num,
            block_id=block_id,
            target_lang=self.target_lang,
            metadata=metadata,
        ))


# ---------------------------------------------------------------------------
# WIP Manager (adapted for DAG node IDs instead of stage numbers)
# ---------------------------------------------------------------------------

class NodeWIPManager:
    """Manages Work-In-Progress files keyed by DAG node ID."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    def save(self, data: Dict[str, Any], filename: str, node_id: str,
             stage_log: Optional[Dict[str, Any]] = None) -> Path:
        """Save WIP file for a node."""
        wip_dir = self.config.get_node_wip_dir(node_id)
        wip_path = wip_dir / f"{filename}.json"

        if not self.config.dry_run:
            with open(wip_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"Saved WIP: {wip_path}")

            if stage_log:
                log_path = wip_dir / f"{filename}_log.json"
                with open(log_path, 'w', encoding='utf-8') as f:
                    json.dump(stage_log, f, ensure_ascii=False, indent=2)
        return wip_path

    def load(self, filename: str, node_id: str) -> Optional[Dict[str, Any]]:
        """Load WIP file for a node."""
        wip_dir = self.config.get_node_wip_dir(node_id)
        wip_path = wip_dir / f"{filename}.json"
        if wip_path.exists():
            with open(wip_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def find_latest_wip(self, filename: str, node_ids: List[str]) -> Optional[Dict[str, Any]]:
        """Find the latest WIP data by trying nodes in reverse order."""
        for node_id in reversed(node_ids):
            data = self.load(filename, node_id)
            if data is not None:
                logger.info(f"Loaded WIP from node '{node_id}'")
                return data
        return None


# ---------------------------------------------------------------------------
# Pipeline Runner
# ---------------------------------------------------------------------------

class PipelineRunner:
    """DAG-driven pipeline execution engine."""

    def __init__(self, dag: DAGDefinition, config: RunnerConfig, progress_db: ProgressDB):
        self.dag = dag
        self.config = config
        self.db = progress_db
        self.wip = NodeWIPManager(config)
        self.processors: Dict[str, StageProcessor] = {}

    def register_processor(self, node_id: str, processor: StageProcessor):
        """Register a processor for a DAG node."""
        self.processors[node_id] = processor

    def resolve_start_node(self, work_id: str,
                           from_node: Optional[str] = None,
                           target_lang: str = "en") -> str:
        """
        Determine where to start execution.

        - If from_node is given, validate it exists in DAG and return it.
        - Otherwise, query progress DB for last completed stage,
          and return the next node in topological order.
        - If no progress exists, return the first node.
        """
        topo = self.dag.topological_sort()

        if from_node:
            if from_node not in self.dag.nodes:
                raise ValueError(
                    f"Node '{from_node}' not in DAG. "
                    f"Available: {', '.join(topo)}"
                )
            return from_node

        # Auto-detect from progress DB (filtered by target language)
        state = self.db.get_latest_state(work_id, target_lang=target_lang)
        last_done = state.get("last_completed_stage")

        if last_done and last_done in self.dag.nodes:
            idx = topo.index(last_done)
            if idx + 1 < len(topo):
                next_node = topo[idx + 1]
                logger.info(
                    f"Auto-resume: last completed='{last_done}', "
                    f"starting from '{next_node}'"
                )
                return next_node

        return topo[0]

    def get_execution_plan(self, start_node: str) -> List[str]:
        """
        Return topological subset of DAG from start_node to terminal nodes.
        """
        return self.dag.get_subgraph_from(start_node)

    def _log_startup_config(self, work_id: str, volume: Optional[str] = None):
        """Log a startup banner showing provider, model, key suffix, DB path, etc."""
        cfg = self.config

        lines = [
            f"  Work: {work_id}" + (f" volume={volume}" if volume else ""),
            f"  Workers: {cfg.max_workers}",
        ]

        # Translation client info
        provider = cfg.provider or "openai"
        model = cfg.model or "(default)"
        try:
            client = _make_translation_client(cfg)
            if hasattr(client, 'key_suffix'):
                suffix = client.key_suffix
                endpoint = getattr(client, 'base_url', None) or f"api.{provider}.com"
                lines.append(f"  Translation: provider={provider} model={model} key=...{suffix} endpoint={endpoint}")
            else:
                lines.append(f"  Translation: provider={provider} model={model}")
        except Exception as e:
            lines.append(f"  Translation: provider={provider} model={model} ERROR={e}")

        # Cleanup client info (if configured)
        if cfg.cleanup_model or cfg.cleanup_provider:
            cp = cfg.cleanup_provider or provider
            cm = cfg.cleanup_model or "(default)"
            try:
                cleanup_client = _make_cleanup_client(cfg)
                if cleanup_client and hasattr(cleanup_client, 'key_suffix'):
                    suffix = cleanup_client.key_suffix
                    endpoint = getattr(cleanup_client, 'base_url', None) or f"api.{cp}.com"
                    lines.append(f"  Cleanup:     provider={cp} model={cm} key=...{suffix} endpoint={endpoint}")
                else:
                    lines.append(f"  Cleanup:     provider={cp} model={cm}")
            except Exception as e:
                lines.append(f"  Cleanup:     provider={cp} model={cm} ERROR={e}")

        # DuckDB info
        lines.append(f"  DuckDB: {self.db.db_path}")

        for line in lines:
            logger.info(line)

    def run(self, work_id: str, volume: Optional[str] = None,
            from_node: Optional[str] = None, resume: bool = False,
            chapter_range: Optional[tuple] = None,
            block_range: Optional[tuple] = None,
            kindle_defer: bool = False,
            skip_kindle: bool = True) -> Dict[str, Any]:
        """
        Execute the pipeline.

        Args:
            work_id: Work number (e.g. "D60")
            volume: Volume letter (e.g. "a")
            from_node: Start from this DAG node (skip predecessors)
            resume: Auto-detect start from progress DB
            chapter_range: (start, end) 1-based inclusive chapter range.
                           end=0 means no upper limit.
            block_range: (start, end) 1-based inclusive block range per chapter.
                         end=0 means no upper limit.
            skip_kindle: Skip Kindle delivery (default True; pass --kindle to enable)

        Returns:
            Pipeline result dict
        """
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        start_time = datetime.now()

        # Resolve start node
        if resume:
            start_node = self.resolve_start_node(work_id, target_lang=self.config.target_lang)
        elif from_node:
            start_node = self.resolve_start_node(work_id, from_node, target_lang=self.config.target_lang)
        else:
            topo = self.dag.topological_sort()
            start_node = topo[0]

        # Build execution plan
        plan = self.get_execution_plan(start_node)
        topo = self.dag.topological_sort()
        skipped = [nid for nid in topo if nid not in plan]

        logger.info(f"Pipeline run: {work_id} (run_id={run_id})")
        self._log_startup_config(work_id, volume)
        logger.info(f"  Execution plan: {' -> '.join(plan)}")
        if skipped:
            logger.info(f"  Skipped (upstream): {', '.join(skipped)}")

        # Create run context
        ctx = RunContext(
            run_id=run_id,
            work_id=work_id,
            volume=volume,
            config=self.config,
            db=self.db,
            dag=self.dag,
            target_lang=self.config.target_lang,
            kindle_defer=kindle_defer,
            skip_kindle=skip_kindle,
        )

        # Load source data
        data = self._load_data(work_id, volume, start_node, plan)
        if data is None:
            return {"success": False, "error": f"Could not load data for {work_id}"}

        # Apply chapter range (1-based inclusive)
        if chapter_range:
            chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
            total_ch = len(chapters)
            cs, ce = chapter_range
            cs_idx = max(0, cs - 1)
            ce_idx = ce if ce > 0 else total_ch
            data["structure"]["body"]["chapters"] = chapters[cs_idx:ce_idx]
            kept = len(data["structure"]["body"]["chapters"])
            logger.info(f"  Chapter range [{cs}-{ce or 'end'}]: kept {kept} of {total_ch}")

            # Slice TOC to match chapter range
            toc = data.get("structure", {}).get("front_matter", {}).get("table_of_contents", {})
            if toc:
                toc_chapters = toc.get("chapters", [])
                if toc_chapters:
                    ce_final = ce if ce > 0 else total_ch
                    filtered_toc = [
                        entry for entry in toc_chapters
                        if cs <= entry.get("chapter_number", 0) <= ce_final
                    ]
                    if filtered_toc:
                        toc["chapters"] = filtered_toc
                        logger.info(f"  TOC sliced to {len(filtered_toc)} entries")

        # Inject split volume metadata (set by --split in CLI)
        if hasattr(self.config, '_split_volume_num') and self.config._split_volume_num:
            meta = data.setdefault("meta", {})
            meta["volume"] = str(self.config._split_volume_num)
            meta["total_volumes"] = self.config._split_total_volumes
            meta["split_volume"] = True
            logger.info(f"  Split volume: {self.config._split_volume_num} of {self.config._split_total_volumes}")

        # Apply block range (1-based inclusive)
        if block_range:
            bs, be = block_range
            for chapter in data.get("structure", {}).get("body", {}).get("chapters", []):
                blocks = chapter.get("content_blocks", [])
                total_bl = len(blocks)
                bs_idx = max(0, bs - 1)
                be_idx = be if be > 0 else total_bl
                chapter["content_blocks"] = blocks[bs_idx:be_idx]
                logger.info(f"  Block range [{bs}-{be or 'end'}]: "
                            f"kept {len(chapter['content_blocks'])} of {total_bl} blocks")

        # Mark skipped nodes
        for nid in skipped:
            self.dag.mark_node(nid, NodeStatus.SKIPPED)
            ctx.emit(nid, "stage_end", "skipped")

        # Execute plan
        stage_results = []
        filename = self._get_filename(work_id, volume)

        for node_id in plan:
            processor = self.processors.get(node_id)
            if not processor:
                logger.warning(f"No processor for node '{node_id}', skipping")
                self.dag.mark_node(node_id, NodeStatus.SKIPPED)
                ctx.emit(node_id, "stage_end", "skipped")
                continue

            node = self.dag.nodes[node_id]
            logger.info(f"\n{'='*60}")
            logger.info(f"  {node.display_name} [{node_id}]")
            logger.info(f"{'='*60}")

            # Check if this is a parallel group
            ready_nodes = self.dag.get_ready_nodes()
            parallel_peers = [
                nid for nid in ready_nodes
                if nid in plan and nid != node_id and nid in self.processors
            ]

            self.dag.mark_node(node_id, NodeStatus.RUNNING)
            ctx.emit(node_id, "stage_start", "running")
            node_start = datetime.now()

            try:
                data = processor.process(data, filename, ctx)

                duration = (datetime.now() - node_start).total_seconds()
                self.dag.mark_node(node_id, NodeStatus.COMPLETED, 100.0)
                ctx.emit(node_id, "stage_end", "completed",
                         metadata={"duration_s": round(duration, 2)})

                # Save WIP
                self.wip.save(data, filename, node_id)

                # Collect stage metrics for summary
                stage_meta = self._collect_stage_metrics(data, node_id)
                stage_results.append({
                    "node": node_id,
                    "name": node.display_name,
                    "success": True,
                    "duration_s": round(duration, 2),
                    **stage_meta,
                })

                # Per-stage one-liner
                self._log_stage_summary(node_id, True, duration, stage_meta)

            except Exception as e:
                duration = (datetime.now() - node_start).total_seconds()
                self.dag.mark_node(node_id, NodeStatus.FAILED)
                ctx.emit(node_id, "stage_end", "failed",
                         metadata={"error": str(e), "duration_s": round(duration, 2)})
                ctx.emit(node_id, "error", "failed",
                         metadata={"error": str(e)})

                logger.error(f"Node '{node_id}' failed: {e}", exc_info=True)
                stage_results.append({
                    "node": node_id,
                    "name": node.display_name,
                    "success": False,
                    "error": str(e),
                    "duration_s": round(duration, 2),
                })

                self._log_stage_summary(node_id, False, duration, {"error": str(e)})
                break  # Stop on failure

        # Save final output
        if not self.config.dry_run and stage_results and stage_results[-1]["success"]:
            output_path = self.config.output_dir / work_id
            # Non-English targets get a language subdirectory
            if self.config.target_lang != "en":
                output_path = output_path / self.config.target_lang
            output_path.mkdir(parents=True, exist_ok=True)

            # Volume-aware filename for split works
            split_vol = data.get("meta", {}).get("split_volume")
            vol_num = data.get("meta", {}).get("volume", "")
            if split_vol and vol_num:
                final_path = output_path / f"translated_{filename}_vol{vol_num}.json"
            else:
                final_path = output_path / f"translated_{filename}.json"
            with open(final_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"\nFinal output: {final_path}")

        total_duration = (datetime.now() - start_time).total_seconds()
        result = {
            "success": all(r["success"] for r in stage_results),
            "work_id": work_id,
            "volume": volume,
            "run_id": run_id,
            "stages": stage_results,
            "duration_s": round(total_duration, 2),
            "plan": plan,
            "skipped": skipped,
        }

        # Include footnote manifest for cross-volume dedup
        if hasattr(ctx, '_footnote_manifest'):
            result["footnote_manifest"] = ctx._footnote_manifest

        # Final summary table
        self._log_final_summary(stage_results, total_duration, result["success"])
        return result

    @staticmethod
    def _collect_stage_metrics(data: Dict[str, Any], node_id: str) -> Dict[str, Any]:
        """Extract summary metrics from data after a stage runs."""
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        metrics: Dict[str, Any] = {}

        if node_id in ("headings", "toc", "metadata"):
            metrics["chapters"] = len(chapters)

        elif node_id == "body":
            total_fn = sum(
                len(b.get("footnotes", []))
                for ch in chapters for b in ch.get("content_blocks", [])
            )
            translated = sum(
                1 for ch in chapters for b in ch.get("content_blocks", [])
                if b.get("translated_content")
            )
            metrics["blocks"] = translated
            metrics["footnotes"] = total_fn

        elif node_id.startswith("cleanup_"):
            total_fn = sum(
                len(b.get("footnotes", []))
                for ch in chapters for b in ch.get("content_blocks", [])
            )
            metrics["footnotes_remaining"] = total_fn

        return metrics

    @staticmethod
    def _log_stage_summary(node_id: str, success: bool, duration: float,
                           meta: Dict[str, Any]):
        """Log a one-line per-stage summary."""
        mark = "ok" if success else "FAIL"
        dur_str = f"{duration / 60:.1f}min" if duration >= 60 else f"{duration:.1f}s"

        parts = [f"  [{mark}] {node_id:<22} {dur_str:>8}"]

        if "chapters" in meta:
            parts.append(f"{meta['chapters']} chapters")
        if "blocks" in meta:
            parts.append(f"{meta['blocks']} blocks")
        if "footnotes" in meta:
            parts.append(f"({meta['footnotes']} footnotes)")
        if "footnotes_remaining" in meta:
            parts.append(f"{meta['footnotes_remaining']} fn remaining")
        if "error" in meta:
            err = str(meta["error"])
            if len(err) > 80:
                err = err[:77] + "..."
            parts.append(err)

        logger.info("  ".join(parts))

    @staticmethod
    def _log_final_summary(stage_results: List[Dict], total_duration: float,
                           success: bool):
        """Log a final summary table."""
        logger.info("")
        logger.info(f"{'='*60}")
        logger.info(f"  Pipeline {'COMPLETED' if success else 'FAILED'} in {total_duration/60:.1f} minutes")
        logger.info(f"{'='*60}")
        logger.info(f"  {'Stage':<22} {'Result':<8} {'Duration':<10} {'Detail'}")
        logger.info(f"  {'─'*22} {'─'*8} {'─'*10} {'─'*30}")

        for r in stage_results:
            mark = "ok" if r["success"] else "FAIL"
            dur = r["duration_s"]
            dur_str = f"{dur/60:.1f}min" if dur >= 60 else f"{dur:.1f}s"
            detail_parts = []
            if "blocks" in r:
                detail_parts.append(f"{r['blocks']} blocks")
            if "footnotes" in r:
                detail_parts.append(f"{r['footnotes']} fn")
            if "footnotes_remaining" in r:
                detail_parts.append(f"{r['footnotes_remaining']} fn left")
            if "chapters" in r:
                detail_parts.append(f"{r['chapters']} ch")
            if "error" in r:
                err = r["error"]
                if len(err) > 40:
                    err = err[:37] + "..."
                detail_parts.append(err)
            detail = ", ".join(detail_parts) if detail_parts else ""
            logger.info(f"  {r['node']:<22} {mark:<8} {dur_str:<10} {detail}")

        logger.info("")

    def _load_data(self, work_id: str, volume: Optional[str],
                   start_node: str, plan: List[str]) -> Optional[Dict[str, Any]]:
        """Load data from WIP or source."""
        filename = self._get_filename(work_id, volume)

        # If starting mid-pipeline, try to load WIP from predecessor
        topo = self.dag.topological_sort()
        start_idx = topo.index(start_node)

        if start_idx > 0:
            predecessors = topo[:start_idx]
            data = self.wip.find_latest_wip(filename, predecessors)
            if data:
                return data
            logger.warning(
                f"No WIP found for predecessors of '{start_node}'. "
                f"Trying source file."
            )

        # Load from source
        return self._load_source(work_id, volume)

    @staticmethod
    def _file_has_chapters(path: Path) -> bool:
        """Quick check whether a source file has non-empty body.chapters."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return bool(data.get("structure", {}).get("body", {}).get("chapters"))
        except Exception:
            return False

    def _load_source(self, work_id: str,
                     volume: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Find and load the source JSON file.

        Searches source_dir first.  If the match has empty chapters (or no
        match is found), falls back to the library directory.
        """
        source_dir = self.config.source_dir
        patterns = []
        if volume:
            patterns.append(f"*{work_id}*{volume}*.json")
            patterns.append(f"*{work_id}{volume}*.json")
        patterns.append(f"*{work_id}*.json")

        # Search primary source dir
        primary_match = None
        for pattern in patterns:
            matches = list(source_dir.rglob(pattern))
            if matches:
                primary_match = matches[0]
                break

        # If primary has chapters, use it
        if primary_match and self._file_has_chapters(primary_match):
            logger.info(f"Loading source: {primary_match}")
            with open(primary_match, 'r', encoding='utf-8') as f:
                return json.load(f)

        # Library fallback (handles empty-chapter COMPLETE_ALL_BOOKS files)
        library_dir = Path("/Users/jacki/project_files/translation_project/library")
        if library_dir.exists():
            for pattern in patterns:
                for lib_pattern in [f"*/cleaned/{pattern}", pattern]:
                    matches = list(library_dir.rglob(lib_pattern))
                    if matches and self._file_has_chapters(matches[0]):
                        if primary_match:
                            logger.warning(
                                f"Primary source has empty chapters — "
                                f"using library fallback: {matches[0]}"
                            )
                        else:
                            logger.info(f"Found source in library: {matches[0]}")
                        with open(matches[0], 'r', encoding='utf-8') as f:
                            return json.load(f)

        # Return primary even if empty (let _ensure_chapters handle it)
        if primary_match:
            logger.info(f"Loading source (may need novella normalization): {primary_match}")
            with open(primary_match, 'r', encoding='utf-8') as f:
                return json.load(f)

        logger.error(f"No source file found for {work_id} in {source_dir}")
        return None

    def _get_filename(self, work_id: str, volume: Optional[str] = None) -> str:
        """Derive filename stem for WIP/output files."""
        # Try to find the actual source filename
        source_dir = self.config.source_dir
        patterns = []
        if volume:
            patterns.append(f"*{work_id}*{volume}*.json")
            patterns.append(f"*{work_id}{volume}*.json")
        patterns.append(f"*{work_id}*.json")

        for pattern in patterns:
            matches = list(source_dir.rglob(pattern))
            if matches:
                return matches[0].stem

        # Fallback
        if volume:
            return f"{work_id}_{volume}"
        return work_id


# ---------------------------------------------------------------------------
# Processor Adapters (wrap existing processors for DAG runner)
# ---------------------------------------------------------------------------

def _make_stage_log(node_id: str, start: datetime, end: datetime,
                    items: int, success: bool,
                    errors: List[str] = None) -> Dict[str, Any]:
    """Create a stage log dict."""
    return {
        "node_id": node_id,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "duration_seconds": (end - start).total_seconds(),
        "items_processed": items,
        "success": success,
        "errors": errors or [],
    }


def _ensure_chapters(data: Dict[str, Any], work_id: str) -> Dict[str, Any]:
    """Ensure body.chapters is non-empty; normalize novellas/short stories.

    If chapters is empty, looks for content in front_matter sections
    and wraps it into a synthetic chapter.  Raises ValueError if
    no translatable content is found anywhere.
    """
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    if chapters:
        return data

    logger.warning(f"{work_id}: body.chapters is empty — checking front_matter for content")

    front = data.get("structure", {}).get("front_matter", {})
    content_blocks = []

    # Check sections first
    for section in front.get("sections", []):
        blocks = section.get("content_blocks", [])
        if blocks:
            content_blocks.extend(blocks)

    # Check introduction
    if not content_blocks:
        intro = front.get("introduction", {})
        blocks = intro.get("content_blocks", [])
        if blocks:
            content_blocks.extend(blocks)

    if not content_blocks:
        raise ValueError(
            f"{work_id}: No translatable content found — "
            f"body.chapters is empty and no content in front_matter. "
            f"Check the source file for structural issues."
        )

    # Build synthetic chapter from front_matter content
    title = data.get("meta", {}).get("title", work_id)
    synthetic_chapter = {
        "chapter_number": 1,
        "title": title,
        "content_blocks": content_blocks,
    }
    data.setdefault("structure", {}).setdefault("body", {})["chapters"] = [synthetic_chapter]
    logger.info(
        f"  Normalized novella: created synthetic chapter with "
        f"{len(content_blocks)} blocks from front_matter"
    )
    return data


def compute_block_checksum(text: str) -> str:
    """Compute SHA256 prefix (16 hex chars) of translated content for dirty detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def stamp_translation_meta(
    block: Dict[str, Any],
    *,
    run_id: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    stage: str = "body",
    target_lang: str = "en",
) -> None:
    """Stamp _translation_meta onto a block after translation.

    The checksum is derived from translated_content so downstream stages
    (and users) can detect manual edits.
    """
    translated = block.get("translated_content", "")
    block["_translation_meta"] = {
        "job_id": run_id,
        "translated_at": datetime.utcnow().isoformat(),
        "provider": provider,
        "model": model,
        "stage": stage,
        "target_lang": target_lang,
        "checksum": compute_block_checksum(translated),
    }


def recompute_block_checksum(block: Dict[str, Any]) -> None:
    """Recompute _translation_meta.checksum after modifying translated_content.

    No-op if _translation_meta is absent (backward compat with pre-Phase-1 JSON).
    """
    meta = block.get("_translation_meta")
    if meta is None:
        return
    translated = block.get("translated_content", "")
    meta["checksum"] = compute_block_checksum(translated)


def recompute_all_checksums(data: Dict[str, Any]) -> int:
    """Recompute _translation_meta.checksum on every block in the data.

    Returns the number of blocks updated.
    """
    count = 0
    for chapter in data.get("structure", {}).get("body", {}).get("chapters", []):
        for block in chapter.get("content_blocks", []):
            if block.get("_translation_meta"):
                recompute_block_checksum(block)
                count += 1
    return count


class SourceLoaderProcessor(StageProcessor):
    """Load and validate source data. This is essentially a pass-through
    since data is already loaded, but it emits progress events and
    normalizes novellas (empty body.chapters)."""

    @property
    def stage_id(self):
        return "source_loader"

    def process(self, data, filename, ctx):
        ctx.emit("source_loader", "stage_start", "running")

        # Normalize novellas / short stories with empty body.chapters
        data = _ensure_chapters(data, ctx.work_id)

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        total_blocks = sum(len(ch.get("content_blocks", [])) for ch in chapters)
        meta = data.get("meta", {})
        logger.info(f"  Source loaded: {len(chapters)} chapters, {total_blocks} blocks")
        logger.info(f"  Work: {meta.get('title_chinese', '?')} by {meta.get('author_chinese', '?')}")

        # Enrich meta from DuckDB catalog (category_english, etc.)
        work_number = meta.get("work_number", ctx.work_id)
        if work_number and not meta.get("category_english"):
            try:
                import duckdb
                from utils.environment_config import get_or_create_config
                env = get_or_create_config()
                conn = duckdb.connect(str(env.catalog_path), read_only=True)
                row = conn.execute(
                    "SELECT category_english, author_chinese, title_chinese "
                    "FROM works WHERE work_number = ?", [work_number]
                ).fetchone()
                conn.close()
                if row:
                    if row[0]:
                        meta["category_english"] = row[0]
                    if row[1] and not meta.get("author_chinese"):
                        meta["author_chinese"] = row[1]
                    if row[2] and not meta.get("title_chinese"):
                        meta["title_chinese"] = row[2]
                    logger.info(f"  Catalog: category={meta.get('category_english', '?')}")
            except Exception as e:
                logger.debug(f"  Catalog enrichment skipped: {e}")

        return data


class MetadataProcessor(StageProcessor):
    """Translate metadata (title, author). Wraps existing MetadataTranslationProcessor."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "metadata"

    def process(self, data, filename, ctx):
        from processors.translator import TranslationService

        meta = data.get('meta', {})
        translator = TranslationService(
            model=self.config.model,
            temperature=self.config.temperature,
            llm_client=_make_translation_client(self.config),
            author=meta.get("author_chinese"),
            genre=meta.get("category_english"),
        )

        items = 0

        if 'title_chinese' in meta and not meta.get('title_english'):
            try:
                resp = translator.translate_from_dict({
                    "content_text_id": 0,
                    "content_source_text": meta['title_chinese'],
                })
                annotated = resp.get('translated_annotated_content', {})
                meta['title_english'] = annotated.get('annotated_content_text', '')
                items += 1
                logger.info(f"  Title: {meta['title_chinese']} -> {meta['title_english']}")
            except Exception as e:
                logger.error(f"  Failed to translate title: {e}")

        if 'author_chinese' in meta and not meta.get('author_english'):
            try:
                resp = translator.translate_from_dict({
                    "content_text_id": 1,
                    "content_source_text": meta['author_chinese'],
                })
                annotated = resp.get('translated_annotated_content', {})
                meta['author_english'] = annotated.get('annotated_content_text', '')
                items += 1
                logger.info(f"  Author: {meta['author_chinese']} -> {meta['author_english']}")
            except Exception as e:
                logger.error(f"  Failed to translate author: {e}")

        data['meta'] = meta
        return data


class TOCProcessor(StageProcessor):
    """Translate TOC entries."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "toc"

    def process(self, data, filename, ctx):
        from processors.translator import TranslationService

        meta = data.get("meta", {})
        translator = TranslationService(
            model=self.config.model,
            temperature=self.config.temperature,
            llm_client=_make_translation_client(self.config),
            author=meta.get("author_chinese"),
            genre=meta.get("category_english"),
        )

        toc = data.get('structure', {}).get('front_matter', {}).get('toc', [])
        items = 0

        for i, entry in enumerate(toc):
            if isinstance(entry, dict):
                full_title = entry.get('full_title', '')
                if entry.get('full_title_english'):
                    items += 1
                    continue
                if full_title:
                    try:
                        resp = translator.translate_from_dict({
                            "content_text_id": i,
                            "content_source_text": full_title,
                        })
                        annotated = resp.get('translated_annotated_content', {})
                        entry['full_title_english'] = annotated.get('annotated_content_text', '')
                        items += 1
                    except Exception as e:
                        logger.error(f"  TOC entry {i} failed: {e}")

        logger.info(f"  Translated {items}/{len(toc)} TOC entries")
        return data


class HeadingsProcessor(StageProcessor):
    """Translate chapter headings using TOC where available."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "headings"

    def process(self, data, filename, ctx):
        from processors.translator import TranslationService

        toc = data.get('structure', {}).get('front_matter', {}).get('toc', [])
        toc_map = {}
        for entry in toc:
            if isinstance(entry, dict):
                ch_num = entry.get('chapter_number')
                en = entry.get('full_title_english', '')
                if ch_num and en:
                    toc_map[ch_num] = en

        import re
        chapters = data.get('structure', {}).get('body', {}).get('chapters', [])
        items = 0

        # First pass: resolve from TOC map or mark as already done
        needs_translation = []  # (chapter_index, ch_num, title_zh)
        for ch_idx, chapter in enumerate(chapters):
            ch_num = chapter.get('chapter_number') or chapter.get('ordinal')
            title_zh = chapter.get('title', '')

            # Already has English — just ensure Chinese is preserved
            if chapter.get('title_english'):
                if title_zh and not chapter.get('title_chinese'):
                    chapter['title_chinese'] = title_zh
                    chapter['title'] = chapter['title_english']
                items += 1
                continue

            if ch_num in toc_map:
                english = toc_map[ch_num]
                english_clean = re.sub(r'\[\d+\]', '', english).strip()
                chapter['title_chinese'] = title_zh
                chapter['title'] = english_clean
                chapter['title_english'] = english_clean
                items += 1
            elif title_zh:
                needs_translation.append((ch_idx, ch_num, title_zh))

        # Translate remaining headings in parallel
        if needs_translation:
            meta = data.get("meta", {})
            translator = TranslationService(
                model=self.config.model,
                temperature=self.config.temperature,
                llm_client=_make_translation_client(self.config),
                author=meta.get("author_chinese"),
                genre=meta.get("category_english"),
            )

            def _translate_heading(entry):
                ch_idx, ch_num, title_zh = entry
                resp = translator.translate_from_dict({
                    "content_text_id": ch_num or 0,
                    "content_source_text": title_zh,
                })
                annotated = resp.get('translated_annotated_content', {})
                return ch_idx, annotated.get('annotated_content_text', '')

            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                futures = {
                    executor.submit(_translate_heading, entry): entry
                    for entry in needs_translation
                }
                for future in as_completed(futures):
                    entry = futures[future]
                    ch_idx, ch_num, title_zh = entry
                    try:
                        _, english = future.result()
                        if english:
                            english_clean = re.sub(r'\[\d+\]', '', english).strip()
                            chapters[ch_idx]['title_chinese'] = title_zh
                            chapters[ch_idx]['title'] = english_clean
                            chapters[ch_idx]['title_english'] = english_clean
                            items += 1
                    except Exception as e:
                        logger.error(f"  Chapter {ch_num} heading failed: {e}")

        # Build lookup maps for TOC update: by chapter_number, ordinal, and chapter_id
        heading_by_num = {}
        heading_by_id = {}
        for ch in chapters:
            en = ch.get('title_english')
            if not en:
                continue
            ch_num = ch.get('chapter_number') or ch.get('ordinal')
            if ch_num:
                heading_by_num[ch_num] = en
            ch_id = ch.get('id')
            if ch_id:
                heading_by_id[ch_id] = en

        def _update_toc_entry(sub):
            ch_num = sub.get('chapter_number')
            ch_id = sub.get('chapter_id')
            en = heading_by_num.get(ch_num) or heading_by_id.get(ch_id)
            if en:
                sub['full_title_chinese'] = sub.get('full_title', '')
                sub['chapter_title_chinese'] = sub.get('chapter_title', '')
                # Strip footnote markers from titles (e.g. [1], [2])
                import re
                en_clean = re.sub(r'\[\d+\]', '', en).strip()
                # Avoid "Chapter 1: Chapter One: ..." duplication
                if re.match(r'(?i)chapter\s', en_clean):
                    sub['full_title'] = en_clean
                else:
                    sub['full_title'] = f"Chapter {ch_num}: {en_clean}"
                sub['chapter_title'] = en_clean
                sub['full_title_english'] = sub['full_title']
                sub['chapter_title_english'] = sub['chapter_title']

        for entry in toc:
            if not isinstance(entry, dict):
                continue
            if 'entries' in entry:
                for sub in entry['entries']:
                    _update_toc_entry(sub)
            else:
                _update_toc_entry(entry)

        logger.info(f"  Translated {items}/{len(chapters)} headings")
        return data


class BodyProcessor(StageProcessor):
    """Translate body content blocks with footnotes."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "body"

    def process(self, data, filename, ctx):
        import re
        from utils.footnote_context import FootnoteContextAccumulator
        from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper

        _DIVIDER_RE = re.compile(r'^[\s※＊\*·•—─━═☆★○●◇◆△▲▽▼■□▪▫\-_=~.。，,]+$')
        _TRANSLATABLE_TYPES = {
            "text", "paragraph", "narrative", "dialogue",
            "verse", "document", "thought", "descriptive",
        }

        def _is_translatable(block):
            if block.get("type") not in _TRANSLATABLE_TYPES:
                return False
            content = block.get("content", "").strip()
            if not content:
                return False
            if _DIVIDER_RE.match(content):
                return False
            return True

        accumulator = FootnoteContextAccumulator()
        meta = data.get("meta", {})
        work_number = meta.get("work_number", ctx.work_id)
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        from utils.environment_config import get_or_create_config
        env = get_or_create_config()

        _author = meta.get("author_chinese")
        _genre = meta.get("category_english")
        logger.info(f"  Body translation: author={_author}, catalog_genre={_genre}")

        wrapper = ContentBlockTranslationWrapper(
            accumulator=accumulator,
            model=self.config.model,
            temperature=self.config.temperature,
            max_retries=self.config.max_retries,
            timeout=self.config.timeout,
            glossary_path=env.glossary_path,
            llm_client=_make_translation_client(self.config),
            target_lang=ctx.target_lang,
            author=_author,
            genre=_genre,
        )

        total_blocks = 0
        successful_blocks = 0
        total_footnotes = 0

        # Flatten all translatable blocks across all chapters into one list
        all_tasks = []  # (ch_idx, block_idx, block)
        for ch_idx, chapter in enumerate(chapters):
            content_blocks = chapter.get("content_blocks", [])
            translatable = [b for b in content_blocks if _is_translatable(b)]
            ch_num = ch_idx + 1
            logger.info(
                f"  Chapter {ch_num}/{len(chapters)}: "
                f"{len(translatable)}/{len(content_blocks)} translatable blocks"
            )
            ctx.emit("body", "chapter_start", "running", chapter_num=ch_num,
                     metadata={"blocks_total": len(translatable)})
            for block_idx, block in enumerate(translatable):
                all_tasks.append((ch_idx, block_idx, block))

        logger.info(f"  Submitting {len(all_tasks)} blocks across {len(chapters)} chapters to {self.config.max_workers} workers")

        # Submit ALL blocks across ALL chapters to one executor
        # Key by (ch_idx, block_id) since block IDs reset per chapter
        results_map = {}  # (ch_idx, block_id) -> result
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {}
            for ch_idx, block_idx, block in all_tasks:
                ch_num = ch_idx + 1
                future = executor.submit(
                    wrapper.execute,
                    content_text_id=block_idx + 1,
                    content_source_text=block["content"],
                    work_id=work_number,
                    chapter_num=ch_num,
                )
                futures[future] = (ch_idx, block)

            for future in as_completed(futures):
                ch_idx, block = futures[future]
                block_id = block.get("id", "unknown")
                try:
                    result = future.result()
                    results_map[(ch_idx, block_id)] = result
                except Exception as e:
                    logger.error(f"  Block {block_id} ch{ch_idx+1} failed: {e}")

        # Apply translations per-chapter in order
        for ch_idx, chapter in enumerate(chapters):
            ch_num = ch_idx + 1
            content_blocks = chapter.get("content_blocks", [])
            ch_footnotes = 0

            for block in content_blocks:
                block_id = block.get("id")
                result = results_map.get((ch_idx, block_id))
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
                    block["content_type"] = annotated.get("content_type", "narrative")

                    # Phase 1: stamp _translation_meta for dirty detection
                    stamp_translation_meta(
                        block,
                        run_id=ctx.run_id,
                        provider=wrapper.provider,
                        model=wrapper.model,
                        stage="body",
                        target_lang=ctx.target_lang,
                    )

                    successful_blocks += 1
                    ch_footnotes += len(block["footnotes"])
                    total_footnotes += len(block["footnotes"])

                    ctx.emit("body", "block_done", "completed",
                             chapter_num=ch_num, block_id=block_id)

            ctx.emit("body", "chapter_end", "completed", chapter_num=ch_num,
                     metadata={"blocks_done": sum(
                         1 for b in content_blocks if b.get("translated_content")
                     ), "footnotes": ch_footnotes})

            logger.info(
                f"  Chapter {ch_num} done: "
                f"{sum(1 for b in content_blocks if b.get('translated_content'))} blocks, "
                f"{ch_footnotes} footnotes"
            )

        logger.info(
            f"  Body complete: {successful_blocks}/{total_blocks} blocks, "
            f"{total_footnotes} footnotes"
        )
        return data


class SpecialSectionsProcessor(StageProcessor):
    """Translate front/back matter."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "special"

    def process(self, data, filename, ctx):
        from processors.translator import TranslationService

        meta = data.get("meta", {})
        translator = TranslationService(
            model=self.config.model,
            temperature=self.config.temperature,
            llm_client=_make_translation_client(self.config),
            author=meta.get("author_chinese"),
            genre=meta.get("category_english"),
        )

        items = 0
        structure = data.get("structure", {})

        # Introduction
        intro = structure.get("front_matter", {}).get("introduction", {})
        if intro and intro.get("content") and not intro.get("translated_content"):
            try:
                resp = translator.translate_from_dict({
                    "content_text_id": 9000,
                    "content_source_text": intro["content"],
                })
                annotated = resp.get("translated_annotated_content", {})
                intro["translated_content"] = annotated.get("annotated_content_text", "")
                items += 1
            except Exception as e:
                logger.error(f"  Introduction failed: {e}")

        # Back matter
        for idx, section in enumerate(structure.get("back_matter", {}).get("sections", [])):
            if section.get("content") and not section.get("translated_content"):
                try:
                    resp = translator.translate_from_dict({
                        "content_text_id": 9100 + idx,
                        "content_source_text": section["content"],
                    })
                    annotated = resp.get("translated_annotated_content", {})
                    section["translated_content"] = annotated.get("annotated_content_text", "")
                    items += 1
                except Exception as e:
                    logger.error(f"  Back matter {idx} failed: {e}")

        logger.info(f"  Translated {items} special sections")
        return data


def _make_translation_client(config: RunnerConfig):
    """Create an LLM client for translation with correct provider routing."""
    from utils.clients.llm_config import get_llm_client
    return get_llm_client(
        component="translator",
        provider=config.provider,
        model=config.model,
    )


def _make_cleanup_client(config: RunnerConfig):
    """Create an LLM client for cleanup using explicit provider/model if given."""
    if config.cleanup_model is not None or config.cleanup_provider is not None:
        from utils.clients.llm_config import get_llm_client
        return get_llm_client(
            component="cleanup",
            provider=config.cleanup_provider,
            model=config.cleanup_model,
        )
    return None  # let TrivialFootnoteRemover use its default


class CharacterCleanupProcessor(StageProcessor):
    """6a: Programmatic cleanup — suppress list + heuristic patterns.

    Phase 0: Build protected set (italicized pinyin terms)
    Phase 1: Suppress-list removal (no API)
    Phase 1.5: Heuristic pattern removal (no API)

    This is fast and free — no API calls.
    """

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "cleanup_6a"

    def process(self, data, filename, ctx):
        from utils.remove_trivial_footnotes import TrivialFootnoteRemover, TrivialityConfig

        kwargs = dict(
            batch_size=self.config.footnote_batch_size,
            triviality_threshold=60,
            cultural_threshold=40,
            create_backup=False,
            max_workers=self.config.max_workers,
        )
        if self.config.cleanup_model is not None:
            kwargs["model"] = self.config.cleanup_model
        triviality_config = TrivialityConfig(**kwargs)
        remover = TrivialFootnoteRemover(triviality_config, client=_make_cleanup_client(self.config))

        # Count baseline
        all_fns = remover.extract_footnotes_with_context(data)
        total_before = len(all_fns)
        remover.result.total_footnotes = total_before
        logger.info(f"  Starting with {total_before} footnotes")

        if not all_fns:
            return data

        # Phase 0: Build protected set
        remover._protected_ideograms = remover._build_protected_set(data)
        remover._protected_seen = set()

        # Phase 1: Suppress-list removal
        suppressed = remover.remove_suppressed_footnotes(data)
        logger.info(f"  Phase 1 (suppress list): removed {suppressed}")

        # Phase 1.5: Heuristic patterns
        heuristic = remover.remove_heuristic_trivial(data)
        logger.info(f"  Phase 1.5 (heuristics): removed {heuristic}")

        remaining = len(remover.extract_footnotes_with_context(data))
        logger.info(f"  After 6a: {remaining} footnotes remain (removed {total_before - remaining})")

        # Recompute checksums after cleanup modified translated_content
        recompute_all_checksums(data)

        # Stash remover on context for 6b to reuse
        ctx._remover = remover

        return data


class TrivialityCleanupProcessor(StageProcessor):
    """6b: AI-powered cleanup — scoring + context-free review.

    Phase 2: AI triviality scoring on remaining footnotes
    Phase 3: Context-free review of survivors by ideogram

    Uses API calls (GPT-4.1-nano or configured model).
    """

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "cleanup_6b"

    def process(self, data, filename, ctx):
        from utils.remove_trivial_footnotes import TrivialFootnoteRemover, TrivialityConfig

        # Try to reuse remover from 6a (has protected set already built)
        remover = getattr(ctx, '_remover', None)
        if remover is None:
            kwargs = dict(
                batch_size=self.config.footnote_batch_size,
                triviality_threshold=60,
                cultural_threshold=40,
                create_backup=False,
                max_workers=self.config.max_workers,
            )
            if self.config.cleanup_model is not None:
                kwargs["model"] = self.config.cleanup_model
            triviality_config = TrivialityConfig(**kwargs)
            remover = TrivialFootnoteRemover(triviality_config, client=_make_cleanup_client(self.config))
            remover._protected_ideograms = remover._build_protected_set(data)
            remover._protected_seen = set()

        # Phase 2: AI scoring
        remaining_fns = remover.extract_footnotes_with_context(data)
        logger.info(f"  Phase 2: scoring {len(remaining_fns)} footnotes via API...")

        if remaining_fns:
            scores = remover.score_all_footnotes(remaining_fns)

            # Build merged prior-volume ideograms for cross-volume dedup
            prior_seen = None
            if self.config.prior_volume_manifests:
                prior_seen = {}
                for m in self.config.prior_volume_manifests:
                    prior_seen.update(m.get("surviving_ideograms", {}))
                logger.info(f"  Cross-volume dedup: {len(prior_seen)} ideograms from "
                            f"{len(self.config.prior_volume_manifests)} prior volume(s)")

            data = remover.remove_trivial_footnotes(data, scores,
                                                     prior_seen_ideograms=prior_seen)
            phase2_removed = remover.result.removed_count
            logger.info(f"  Phase 2 removed {phase2_removed} via AI scoring")

        # Phase 3: Context-free review by ideogram
        logger.info("  Phase 3: context-free review of survivors...")
        phase3_removed = remover.review_survivors_by_ideogram(data)
        logger.info(f"  Phase 3 removed {phase3_removed} via context-free review")

        remaining = len(remover.extract_footnotes_with_context(data))
        logger.info(f"  After 6b: {remaining} footnotes remain")

        # Recompute checksums after cleanup modified translated_content
        recompute_all_checksums(data)

        # Stash remover for 6c
        ctx._remover = remover

        return data


class DensityValidationProcessor(StageProcessor):
    """6c: Post-cleanup finalization.

    - Intra-block dedup
    - Marker repositioning (word-boundary checks)
    - Unanchored footnote removal
    - Chapter-continuous renumbering
    - Orphan marker sanitization
    - AI marker-position verification
    - Final integrity validation
    """

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "cleanup_6c"

    def process(self, data, filename, ctx):
        from utils.remove_trivial_footnotes import (
            _dedup_intra_block,
            _anchor_footnotes_to_first_occurrence,
            _reposition_markers,
            _renumber_chapter_continuous,
            _sanitize_orphan_markers,
            _ai_verify_marker_positions,
            _italicize_pinyin_in_footnotes,
            validate_footnote_integrity,
        )

        # Intra-block dedup
        intra_deduped = _dedup_intra_block(data)
        if intra_deduped:
            logger.info(f"  Removed {intra_deduped} intra-block duplicate footnotes")

        # Anchor footnotes to first occurrence of their ideogram
        anchored = _anchor_footnotes_to_first_occurrence(data)
        if anchored:
            logger.info(f"  Relocated {anchored} footnotes to first-occurrence blocks")

        # Reposition markers + remove unanchored
        repos_count, unanchored_count = _reposition_markers(data)
        if repos_count:
            logger.info(f"  Repositioned {repos_count} footnote markers")
        if unanchored_count:
            logger.info(f"  Removed {unanchored_count} unanchored footnotes")

        # Renumber
        _renumber_chapter_continuous(data)
        logger.info("  Renumbered footnotes continuously per chapter")

        # Sanitize orphan markers
        orphans_fixed = _sanitize_orphan_markers(data)
        if orphans_fixed:
            logger.info(f"  Sanitized orphan markers in {orphans_fixed} blocks")

        # AI marker-position verification
        remover = getattr(ctx, '_remover', None)
        if remover and hasattr(remover, 'client'):
            logger.info("  AI marker-position verification...")
            ai_repos = _ai_verify_marker_positions(data, remover.client)
            if ai_repos:
                logger.info(f"  AI repositioned {ai_repos} misplaced markers")
                _renumber_chapter_continuous(data)
                orphans_2 = _sanitize_orphan_markers(data)
                if orphans_2:
                    logger.info(f"  Post-AI: sanitized {orphans_2} orphan markers")

        # Italicize pinyin terms in footnote explanations
        italicized = _italicize_pinyin_in_footnotes(data)
        if italicized:
            logger.info(f"  Italicized pinyin in {italicized} footnote explanations")

        # Final count
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        total_fn = sum(
            len(b.get("footnotes", []))
            for ch in chapters
            for b in ch.get("content_blocks", [])
        )
        logger.info(f"  Final footnote count: {total_fn}")

        # Recompute checksums after all cleanup modifications
        recompute_all_checksums(data)

        # Validate integrity
        validation = validate_footnote_integrity(data)
        logger.info(f"  Integrity: {'PASSED' if validation['passed'] else 'FAILED'}")
        if not validation["passed"]:
            for err in validation["errors"][:5]:
                logger.warning(f"    {err}")

        # Extract cross-volume footnote manifest and stash on context
        from utils.remove_trivial_footnotes import extract_footnote_manifest
        manifest = extract_footnote_manifest(data, ctx.work_id, ctx.volume or "")
        ctx._footnote_manifest = manifest
        logger.info(f"  Footnote manifest: {len(manifest['surviving_ideograms'])} ideograms, "
                    f"{len(manifest['surviving_pinyin'])} pinyin terms")

        # Persist manifest to disk for resume across interrupted multi-volume runs
        manifest_dir = self.config.wip_dir / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        # Use split volume label if this is a split work, otherwise volume letter
        split_vol = data.get("meta", {}).get("split_volume")
        if split_vol:
            vol_label = f"split{data['meta']['volume']}"
        else:
            vol_label = ctx.volume or "single"
        manifest_path = manifest_dir / f"{ctx.work_id}_{vol_label}_footnote_manifest.json"
        if not self.config.dry_run:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            logger.info(f"  Manifest saved: {manifest_path}")

        return data


class FootnoteIntegrityGate(StageProcessor):
    """Quality gate: validate footnote markers match definitions."""

    @property
    def stage_id(self):
        return "qg_footnote_integrity"

    def process(self, data, filename, ctx):
        from utils.remove_trivial_footnotes import validate_footnote_integrity

        result = validate_footnote_integrity(data)
        if result["passed"]:
            logger.info("  Footnote integrity: PASSED")
        else:
            logger.warning(f"  Footnote integrity: FAILED ({len(result['errors'])} issues)")
            for err in result["errors"][:5]:
                logger.warning(f"    {err}")
            # Quality gates don't halt by default — just warn
        return data


class DramatisPersonaeProcessor(StageProcessor):
    """6d: Harvest character footnotes into Dramatis Personae.

    - Identifies character-name footnotes (fictional + historical)
    - Harvests into a structured DP list
    - Strips character footnotes from body text
    - Renumbers remaining footnotes
    - Optionally validates uncertain entries via DeepSeek
    """

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "cleanup_6d_dramatis"

    def process(self, data, filename, ctx):
        from utils.build_dramatis_personae import build_dramatis_personae

        # Use cleanup client if configured, otherwise fall back to translation client
        client = _make_cleanup_client(self.config) or _make_translation_client(self.config)

        dp_entries = build_dramatis_personae(
            data,
            client=client,
            validate_historical=True,
        )

        n_hist = sum(1 for e in dp_entries if e.get("dp_type") == "historical")
        n_fict = sum(1 for e in dp_entries if e.get("dp_type", "fictional") == "fictional")
        n_group = sum(1 for e in dp_entries if e.get("dp_type") == "group")
        logger.info(
            f"  Dramatis Personae: {len(dp_entries)} entries "
            f"({n_hist} historical, {n_fict} fictional, {n_group} groups)"
        )

        # Count remaining footnotes
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        remaining = sum(
            len(b.get("footnotes", []))
            for ch in chapters
            for b in ch.get("content_blocks", [])
        )
        logger.info(f"  After DP harvest: {remaining} footnotes remain in body")

        # Recompute checksums after DP harvest modified blocks
        recompute_all_checksums(data)

        return data


class PostCleanupGate(StageProcessor):
    """Quality gate: validate footnotes after cleanup passes."""

    @property
    def stage_id(self):
        return "qg_post_cleanup"

    def process(self, data, filename, ctx):
        from utils.remove_trivial_footnotes import validate_footnote_integrity

        result = validate_footnote_integrity(data)
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        total_fn = sum(
            len(b.get("footnotes", []))
            for ch in chapters
            for b in ch.get("content_blocks", [])
        )

        logger.info(f"  Post-cleanup: {total_fn} footnotes, "
                     f"integrity={'PASSED' if result['passed'] else 'FAILED'}")
        return data


class CorrectionClassifyProcessor(StageProcessor):
    """Nano-based classifier: tag each block with issue categories."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "correction_classify"

    def process(self, data, filename, ctx):
        from processors.correction_classifier import CorrectionClassifier

        classifier = CorrectionClassifier(
            max_workers=min(50, self.config.max_workers * 5),
        )
        data = classifier.classify_work(data)

        # Store summary
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        tagged = sum(
            1 for ch in chapters for b in ch.get("content_blocks", [])
            if b.get("_correction_tags") and b["_correction_tags"] != ["clean"]
        )
        total = sum(
            1 for ch in chapters for b in ch.get("content_blocks", [])
            if b.get("_correction_tags") is not None
        )
        logger.info(f"  Classification: {tagged}/{total} blocks tagged for correction")
        return data


class CorrectionApplyProcessor(StageProcessor):
    """Apply focused specialist corrections to tagged blocks only."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "correction_apply"

    def process(self, data, filename, ctx):
        from processors.correction_applicator import CorrectionApplicator

        applicator = CorrectionApplicator(
            model=self.config.cleanup_model or "deepseek-chat",
            provider=self.config.cleanup_provider or "deepseek",
            max_workers=min(50, self.config.max_workers * 5),
        )

        # Build cross-volume dedup sets from prior manifests
        prior_ideo = None
        prior_pinyin = None
        if self.config.prior_volume_manifests:
            prior_ideo = set()
            prior_pinyin = set()
            for m in self.config.prior_volume_manifests:
                prior_ideo.update(m.get("surviving_ideograms", {}).keys())
                prior_pinyin.update(m.get("surviving_pinyin", []))

        data = applicator.correct_work(data,
                                        prior_seen_ideograms=prior_ideo,
                                        prior_seen_pinyin=prior_pinyin)
        return data


class WikiEnrichmentProcessor(StageProcessor):
    """Enrich footnotes with Wikipedia summaries via historical_ref_cache."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "wiki_enrich"

    def process(self, data, filename, ctx):
        from utils.historical_ref_cache import enrich_work_footnotes

        work_id = data.get("meta", {}).get("work_number", "")
        logger.info(f"  Wiki enrichment for {work_id or filename}...")

        data = enrich_work_footnotes(data, work_id=work_id)
        return data


class ValidationProcessor(StageProcessor):
    """Final validation of translation completeness."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "validation"

    def process(self, data, filename, ctx):
        import re
        from utils.remove_trivial_footnotes import validate_footnote_integrity

        _DIVIDER_RE = re.compile(r'^[\s※＊\*·•—─━═☆★○●◇◆△▲▽▼■□▪▫\-_=~.。，,]+$')
        _TRANSLATABLE_TYPES = {
            "text", "paragraph", "narrative", "dialogue",
            "verse", "document", "thought", "descriptive",
        }

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        total_blocks = 0
        translated_blocks = 0
        total_footnotes = 0
        issues = []

        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                btype = block.get("type")
                content = block.get("content", "").strip()
                if btype not in _TRANSLATABLE_TYPES or not content or _DIVIDER_RE.match(content):
                    continue
                total_blocks += 1
                if block.get("translated_content"):
                    translated_blocks += 1
                total_footnotes += len(block.get("footnotes", []))

        coverage = translated_blocks / total_blocks * 100 if total_blocks else 0
        if coverage < 90:
            issues.append(f"Low coverage: {coverage:.1f}% ({translated_blocks}/{total_blocks})")

        integrity = validate_footnote_integrity(data)
        if not integrity["passed"]:
            issues.extend(integrity["errors"][:10])

        # Check for stale checksums (blocks manually edited after translation)
        stale_blocks = 0
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                meta = block.get("_translation_meta")
                if meta and block.get("translated_content"):
                    expected = compute_block_checksum(block["translated_content"])
                    if meta.get("checksum") != expected:
                        stale_blocks += 1
        if stale_blocks:
            logger.warning(f"  {stale_blocks} blocks have stale checksums (manually edited)")

        logger.info(f"  Coverage: {coverage:.1f}% ({translated_blocks}/{total_blocks})")
        logger.info(f"  Footnotes: {total_footnotes}")
        logger.info(f"  Integrity: {'PASSED' if integrity['passed'] else 'FAILED'}")

        data.setdefault("meta", {}).setdefault("translation", {})["validation"] = {
            "coverage_pct": round(coverage, 1),
            "total_blocks": total_blocks,
            "translated_blocks": translated_blocks,
            "total_footnotes": total_footnotes,
            "footnote_integrity": integrity["passed"],
            "stale_checksum_blocks": stale_blocks,
            "issues": issues,
        }
        return data


class ConsistencyReviewProcessor(StageProcessor):
    """Optional: chapter-level consistency review using DeepSeek V3.

    Reviews translated chapters for cross-block issues (tense, gender,
    style, footnotes, pinyin) and applies corrections.
    """

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "review"

    def process(self, data, filename, ctx):
        from processors.consistency_reviewer import ConsistencyReviewer

        reviewer = ConsistencyReviewer(
            model=self.config.cleanup_model or "deepseek-chat",
            provider=self.config.cleanup_provider or "deepseek",
            max_workers=self.config.max_workers,
        )
        reports = reviewer.review_work(data, ctx.work_id)

        total_findings = sum(r["summary"]["total_findings"] for r in reports)
        logger.info(f"  Consistency review: {total_findings} findings across {len(reports)} chapters")

        # Save per-chapter review JSONs to WIP
        wip_dir = self.config.get_node_wip_dir("review")
        for report in reports:
            ch_path = wip_dir / f"{filename}_ch{report['chapter']}_review.json"
            with open(ch_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

        # Do NOT auto-apply — findings go to the adjudicator stage
        # Store reports in data for the adjudicator to pick up
        data.setdefault("meta", {}).setdefault("translation", {})["review"] = {
            "total_findings": total_findings,
            "by_category": {
                cat: sum(r["summary"]["by_category"].get(cat, 0) for r in reports)
                for cat in ("tense", "gender", "style", "register", "honorific", "footnote", "pinyin", "weapon", "idiom", "date")
            },
            "chapters_reviewed": len(reports),
        }
        data["_review_reports"] = reports
        return data


class ReviewAdjudicateProcessor(StageProcessor):
    """LLM adjudication of review findings — accept or reject each proposed change."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "review_adjudicate"

    def process(self, data, filename, ctx):
        from processors.consistency_reviewer import ConsistencyReviewer, ReviewAdjudicator

        reports = data.pop("_review_reports", None)
        if not reports:
            # Try loading from WIP
            wip_dir = self.config.get_node_wip_dir("review")
            reports = []
            if wip_dir.exists():
                for review_file in sorted(wip_dir.glob(f"{filename}_ch*_review.json")):
                    with open(review_file, 'r', encoding='utf-8') as f:
                        reports.append(json.load(f))

        total_findings = sum(r.get("summary", {}).get("total_findings", 0) for r in reports)
        if total_findings == 0:
            logger.info("  No review findings to adjudicate")
            return data

        adjudicator = ReviewAdjudicator(
            model=self.config.cleanup_model or "deepseek-chat",
            provider=self.config.cleanup_provider or "deepseek",
            max_workers=min(50, self.config.max_workers * 5),
        )
        reports = adjudicator.adjudicate_reports(reports, data)

        # Save adjudicated reports to WIP
        wip_dir = self.config.get_node_wip_dir("review_adjudicate")
        wip_dir.mkdir(parents=True, exist_ok=True)
        for report in reports:
            ch_path = wip_dir / f"{filename}_ch{report['chapter']}_adjudicated.json"
            with open(ch_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

        # Apply only accepted findings
        reviewer = ConsistencyReviewer()
        data = reviewer.apply_findings(data, reports, respect_accepted=True)

        accepted = sum(
            1 for r in reports for f in r.get("findings", []) if f.get("accepted") is True
        )
        rejected = sum(
            1 for r in reports for f in r.get("findings", []) if f.get("accepted") is False
        )
        logger.info(f"  Adjudication: {accepted} accepted, {rejected} rejected out of {total_findings}")

        data.setdefault("meta", {}).setdefault("translation", {})["review_adjudicate"] = {
            "total_findings": total_findings,
            "accepted": accepted,
            "rejected": rejected,
        }
        return data


class EpubBuildProcessor(StageProcessor):
    """Build EPUB from translated JSON."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "epub_build"

    def process(self, data, filename, ctx):
        from builders.epub_builder import EpubBuilder
        from pathlib import Path

        # Auto-detect cover from portfolio assignment
        cover_image = None
        try:
            import duckdb
            db_path = Path(self.config.catalog_path).parent / "artwork_portfolio.duckdb"
            if db_path.exists():
                db = duckdb.connect(str(db_path), read_only=True)
                row = db.execute(
                    "SELECT ai.cached_path FROM artwork_assignments aa "
                    "JOIN artwork_images ai ON aa.image_id = ai.image_id "
                    "WHERE aa.work_number = ?", [ctx.work_id]
                ).fetchone()
                db.close()
                if row and row[0]:
                    cover_path = Path(row[0])
                    if cover_path.exists():
                        cover_image = cover_path
                        logger.info(f"  Cover image: {cover_path.name}")
        except Exception as e:
            logger.debug(f"  No portfolio cover: {e}")

        # Build cover subtitle from metadata
        cover_subtitle = None
        volume = data.get("meta", {}).get("volume", "")
        if volume:
            vol_word = {1:"One",2:"Two",3:"Three",4:"Four",5:"Five"}.get(
                int(volume) if str(volume).isdigit() else 0, str(volume))
            cover_subtitle = f"A Classic Chinese Novel in a New Translation\nVolume {vol_word}"

        builder = EpubBuilder(cover_image=cover_image, cover_subtitle=cover_subtitle,
                              include_source=self.config.include_source)
        output_dir = self.config.output_dir / ctx.work_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = builder._english_epub_path(data, output_dir)
        result = builder.build_from_data(data, output_path)

        size_kb = result.stat().st_size / 1024
        logger.info(f"  EPUB: {result.name} ({size_kb:.1f} KB)")
        return data


class SendKindleProcessor(StageProcessor):
    """Email EPUB to Kindle device(s) via Send-to-Kindle service."""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "send_kindle"

    def process(self, data, filename, ctx):
        from delivery.kindle_sender import KindleSender

        # In series mode, Kindle delivery is deferred to batch send at end
        if getattr(ctx, 'kindle_defer', False):
            logger.info("  Kindle delivery deferred (series mode — will batch send at end)")
            return data

        # Skip unless --kindle flag was passed
        if getattr(ctx, 'skip_kindle', True):
            logger.info("  Kindle delivery skipped (use --kindle to enable)")
            return data

        sender = KindleSender()

        # Skip silently if no Kindle config
        if not sender.kindle_emails:
            logger.info("  No KINDLE_EMAILS configured — skipping Kindle delivery")
            return data

        # Find EPUB from previous stage
        epub_dir = self.config.output_dir / ctx.work_id
        epubs = sorted(epub_dir.glob("*.epub"))
        if not epubs:
            logger.warning("  No EPUB found to send")
            return data

        epub_path = epubs[-1]
        logger.info(f"  Sending {epub_path.name} to Kindle...")

        try:
            results = sender.send(epub_path, dry_run=self.config.dry_run)
            succeeded = sum(1 for v in results.values() if v)
            failed = len(results) - succeeded
            if failed:
                logger.warning(f"  Kindle delivery: {succeeded} succeeded, {failed} failed")
            else:
                logger.info(f"  Kindle delivery: {succeeded}/{len(results)} succeeded")
        except Exception as e:
            # Never fail the pipeline on send errors — the translation is already saved
            logger.error(f"  Kindle delivery error (non-fatal): {e}")

        return data


class TermConsistencyProcessor(StageProcessor):
    """Detect and fix inconsistent term renderings across the work.

    Phase 0: Programmatic split of compound footnotes (、 and 與 separators)
    Phase 0.5: DeepSeek split of ambiguous compounds (6+ char ideograms)
    Phase 1: Footnote-based inconsistency detection
    Phase 2: Glossary-driven variant standardization
    """

    def __init__(self, config: RunnerConfig):
        self.config = config

    @property
    def stage_id(self):
        return "term_consistency"

    def process(self, data, filename, ctx):
        from utils.term_consistency import standardize_work

        # Load glossary for authoritative renderings
        glossary = None
        try:
            from utils.glossary import TranslationGlossary
            glossary = TranslationGlossary()
        except Exception as e:
            logger.warning(f"  Could not load glossary (proceeding without): {e}")

        # DeepSeek client for compound footnote splitting
        deepseek_client = None
        try:
            from utils.clients.llm_config import get_llm_client
            deepseek_client = get_llm_client(provider="deepseek")
        except Exception as e:
            logger.warning(f"  Could not initialize DeepSeek for compound splitting: {e}")

        data, report = standardize_work(data, glossary=glossary, llm_client=deepseek_client)

        logger.info(f"  Term consistency: {report['inconsistencies_found']} inconsistencies, "
                    f"{report['replacements_made']} replacements")

        if report["glossary_candidates"]:
            logger.info(f"  Glossary candidates (not yet in DB):")
            for cand in report["glossary_candidates"]:
                logger.info(f"    {cand['ideogram']} → \"{cand['recommended_form']}\"")

        # Save report to WIP
        wip_dir = self.config.get_node_wip_dir("term_consistency")
        report_path = wip_dir / f"{filename}_consistency_report.json"
        if not self.config.dry_run:
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            logger.info(f"  Report saved: {report_path}")

        return data


# ---------------------------------------------------------------------------
# Factory: build_pipeline
# ---------------------------------------------------------------------------

def build_pipeline(config: RunnerConfig,
                   progress_db: ProgressDB,
                   verify_clients: bool = True) -> PipelineRunner:
    """Factory: create a fully wired PipelineRunner.

    Args:
        config: Pipeline configuration.
        progress_db: Progress database.
        verify_clients: If True, send a test API call to each LLM client
                        at startup. Fails fast on bad credentials.
    """
    dag = create_v2_pipeline_dag()
    runner = PipelineRunner(dag, config, progress_db)

    # Verify LLM clients upfront (fail fast on bad API keys)
    if verify_clients:
        logger.info("Verifying LLM clients...")
        try:
            translation_client = _make_translation_client(config)
            if hasattr(translation_client, 'verify'):
                translation_client.verify()
        except Exception as e:
            raise RuntimeError(f"Translation client verification failed: {e}") from e

        try:
            cleanup_client = _make_cleanup_client(config)
            if cleanup_client and hasattr(cleanup_client, 'verify'):
                cleanup_client.verify()
        except Exception as e:
            raise RuntimeError(f"Cleanup client verification failed: {e}") from e

    runner.register_processor("source_loader", SourceLoaderProcessor())
    runner.register_processor("metadata", MetadataProcessor(config))
    runner.register_processor("toc", TOCProcessor(config))
    runner.register_processor("headings", HeadingsProcessor(config))
    runner.register_processor("body", BodyProcessor(config))
    runner.register_processor("special", SpecialSectionsProcessor(config))
    runner.register_processor("cleanup_6a", CharacterCleanupProcessor(config))
    runner.register_processor("cleanup_6b", TrivialityCleanupProcessor(config))
    runner.register_processor("cleanup_6c", DensityValidationProcessor(config))
    runner.register_processor("cleanup_6d_dramatis", DramatisPersonaeProcessor(config))
    runner.register_processor("qg_footnote_integrity", FootnoteIntegrityGate())
    runner.register_processor("qg_post_cleanup", PostCleanupGate())
    runner.register_processor("correction_classify", CorrectionClassifyProcessor(config))
    runner.register_processor("correction_apply", CorrectionApplyProcessor(config))
    runner.register_processor("term_consistency", TermConsistencyProcessor(config))
    runner.register_processor("wiki_enrich", WikiEnrichmentProcessor(config))
    runner.register_processor("validation", ValidationProcessor(config))
    runner.register_processor("review", ConsistencyReviewProcessor(config))
    runner.register_processor("review_adjudicate", ReviewAdjudicateProcessor(config))
    runner.register_processor("epub_build", EpubBuildProcessor(config))
    runner.register_processor("send_kindle", SendKindleProcessor(config))

    return runner


# ---------------------------------------------------------------------------
# Series Orchestration
# ---------------------------------------------------------------------------

def run_series(
    series_name: str,
    config: RunnerConfig,
    progress_db: ProgressDB,
    from_node: Optional[str] = None,
    resume: bool = False,
) -> Dict[str, Any]:
    """
    Run the full pipeline for every work in a series, in order.

    Multi-volume works iterate volumes sequentially (a, b, c, ...).
    Kindle delivery is deferred until the entire series completes —
    all EPUBs are sent in a single batch at the end.

    Args:
        series_name: Series name (e.g. "Condor Trilogy") or path.
        config: Pipeline configuration.
        progress_db: Progress database.
        from_node: Start from this DAG node for each work.
        resume: Auto-resume each work from its last checkpoint.

    Returns:
        Result dict with per-work results and series-level summary.
    """
    from utils.library_resolver import resolve_series

    start_time = datetime.now()
    works = resolve_series(series_name)

    if not works:
        return {
            "success": False,
            "error": f"No works found for series '{series_name}'",
            "work_results": [],
            "duration_s": 0,
        }

    logger.info(f"\n{'='*60}")
    logger.info(f"  Series: {series_name}")
    logger.info(f"  Works:  {len(works)}")
    for w in works:
        vols = f" (volumes: {', '.join(w.volumes)})" if w.volumes else ""
        logger.info(f"    {w.order_in_series or '?'}. {w.work_id} — {w.title_english}{vols}")
    logger.info(f"{'='*60}\n")

    work_results = []
    collected_epubs = []

    for work in works:
        volumes = work.volumes or [None]
        for volume in volumes:
            vol_str = f" volume={volume}" if volume else ""
            logger.info(f"\n{'─'*60}")
            logger.info(f"  Starting: {work.work_id}{vol_str} — {work.title_english}")
            logger.info(f"{'─'*60}")

            # Build a fresh pipeline for each work (clean DAG state)
            runner = build_pipeline(config, progress_db, verify_clients=(len(work_results) == 0))

            work_start = datetime.now()
            try:
                result = runner.run(
                    work_id=work.work_id,
                    volume=volume,
                    from_node=from_node,
                    resume=resume,
                    kindle_defer=True,  # Batch send at series end
                )
                work_duration = (datetime.now() - work_start).total_seconds()
                result["duration_s"] = round(work_duration, 2)

                work_results.append({
                    "work_id": work.work_id,
                    "volume": volume,
                    "title": work.title_english,
                    "success": result["success"],
                    "duration_s": round(work_duration, 2),
                })

                # Collect EPUBs for batch Kindle delivery
                if result["success"]:
                    epub_dir = config.output_dir / work.work_id
                    if epub_dir.exists():
                        for epub in epub_dir.glob("*.epub"):
                            collected_epubs.append(epub)

            except Exception as e:
                work_duration = (datetime.now() - work_start).total_seconds()
                logger.error(f"  Work {work.work_id}{vol_str} failed: {e}")
                work_results.append({
                    "work_id": work.work_id,
                    "volume": volume,
                    "title": work.title_english,
                    "success": False,
                    "error": str(e),
                    "duration_s": round(work_duration, 2),
                })

    # Batch Kindle delivery at series end
    kindle_sent = []
    if collected_epubs and not config.dry_run:
        kindle_sent = _send_series_to_kindle(series_name, collected_epubs)

    total_duration = (datetime.now() - start_time).total_seconds()
    all_succeeded = all(r["success"] for r in work_results)

    return {
        "success": all_succeeded,
        "series": series_name,
        "work_results": work_results,
        "kindle_sent": kindle_sent,
        "duration_s": round(total_duration, 2),
    }


def _send_series_to_kindle(series_name: str, epub_paths: List[Path]) -> List[str]:
    """Send all EPUBs from a series to Kindle in batch."""
    from delivery.kindle_sender import KindleSender

    sender = KindleSender()
    if not sender.kindle_emails:
        logger.info("  No KINDLE_EMAILS configured — skipping series Kindle delivery")
        return []

    logger.info(f"\n  Sending {len(epub_paths)} EPUBs from '{series_name}' to Kindle...")
    sent = []
    for epub_path in epub_paths:
        try:
            results = sender.send(epub_path)
            if any(results.values()):
                sent.append(epub_path.name)
                logger.info(f"    Sent: {epub_path.name}")
            else:
                logger.warning(f"    Failed: {epub_path.name}")
        except Exception as e:
            logger.error(f"    Kindle error for {epub_path.name}: {e}")

    logger.info(f"  Kindle delivery: {len(sent)}/{len(epub_paths)} EPUBs sent")
    return sent
