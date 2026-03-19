"""
Workflow Node Wrappers

This package contains workflow node wrappers that provide clean, workflow-ready
interfaces around existing translation utilities.

Wrappers handle:
- Business rules and success criteria
- Data quality validation (pre/post checks)
- Manifest generation (input/output tracking, metadata)
- Structured logging (JSON logs, progress reports)
- Error handling with retry policies
- Contract validation (input/output schemas)
"""

from wrappers.content_block_translation_wrapper import (
    ContentBlockTranslationWrapper,
    TranslationResult,
)

from wrappers.volume_translation_wrapper import (
    VolumeTranslationWrapper,
    VolumeTranslationResult,
    VolumeStatistics,
    AggregateValidationReport,
    BlockResult,
    BlockTypeStats
)

__all__ = [
    # Block-level translation
    "ContentBlockTranslationWrapper",
    "TranslationResult",

    # Volume-level translation
    "VolumeTranslationWrapper",
    "VolumeTranslationResult",
    "VolumeStatistics",
    "AggregateValidationReport",
    "BlockResult",
    "BlockTypeStats"
]
