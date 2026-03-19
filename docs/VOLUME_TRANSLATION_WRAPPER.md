# Volume Translation Wrapper

Complete guide to using the VolumeTranslationWrapper for parallel volume-level translation.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Statistics & Validation](#statistics--validation)
- [Integration with Translation Pipeline](#integration-with-translation-pipeline)
- [Performance](#performance)
- [Error Handling](#error-handling)
- [API Reference](#api-reference)

## Overview

The **VolumeTranslationWrapper** orchestrates parallel translation of entire volumes using a fan-out/fan-in pattern with aggregate validation.

### Key Features

- **Parallel Processing**: Translate multiple content blocks concurrently (configurable workers)
- **Aggregate Validation**: Ensure average quality >= 9.5 and zero footnote mismatches across entire volume
- **Statistics Breakdown**: Separate metrics for body vs non-body content
- **Progress Tracking**: Real-time progress bars with quality metrics
- **Structured Logging**: Comprehensive manifest generation
- **Integration**: Seamlessly replaces sequential processing in translation pipeline

### Benefits

- **5-10x faster** than sequential block processing
- **Quality assurance** at aggregate level
- **Insights** into body vs non-body translation patterns
- **Resume capability** through checkpoint integration (future)

## Architecture

```
VolumeTranslationWrapper
    ↓
[Extract & Categorize Blocks]
    ├─→ Body blocks (chapters)
    └─→ Non-body blocks (metadata, TOC, front/back matter)
    ↓
[Fan-Out: Parallel Translation]
    ├─→ ContentBlockTranslationWrapper (block 1) [Worker 1]
    ├─→ ContentBlockTranslationWrapper (block 2) [Worker 2]
    ├─→ ContentBlockTranslationWrapper (block 3) [Worker 3]
    ├─→ ContentBlockTranslationWrapper (block N) [Worker M]
    ↓
[Fan-In: Collect Results]
    └─→ Progress bar with real-time metrics
    ↓
[Calculate Statistics]
    ├─→ Overall metrics (total, success rate, avg quality)
    ├─→ Body metrics (chapter content)
    └─→ Non-body metrics (metadata, TOC, etc.)
    ↓
[Aggregate Validation]
    ├─→ Average quality >= threshold?
    ├─→ Total footnote mismatches = 0?
    └─→ All blocks succeeded?
    ↓
[Reconstruct Volume]
    └─→ Merge translated blocks into volume structure
    ↓
[Generate Manifest]
    └─→ Comprehensive processing report
```

## Quick Start

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Verify installation
python -c "from wrappers import VolumeTranslationWrapper; print('OK')"
```

### Basic Usage

```python
from wrappers import VolumeTranslationWrapper

# Load your volume data
import json
with open("cleaned_volume.json", "r") as f:
    volume_data = json.load(f)

# Initialize wrapper with default config
wrapper = VolumeTranslationWrapper()

# Execute translation
result = wrapper.execute(
    volume_data=volume_data,
    work_id="D1379"
)

# Check result
if result.success:
    print(f"✓ Translation successful!")
    print(f"  Average quality: {result.statistics.average_quality:.1f}/10")
    print(f"  Total blocks: {result.statistics.total_blocks}")
    print(f"  Time: {result.statistics.total_translation_time:.1f}s")

    # Save translated volume
    with open("translated_volume.json", "w") as f:
        json.dump(result.translated_volume, f, indent=2, ensure_ascii=False)
else:
    print(f"✗ Translation failed")
    print(f"  Errors: {result.validation_report.validation_errors}")
```

## Configuration

### Configuration Priority

Configuration is loaded with the following priority (highest to lowest):

1. **Direct kwargs** - Parameters passed to `__init__`
2. **Work-specific override** - `config/volume_work_overrides/{work_id}_rules.yaml`
3. **Named config** - `config/volume_translation_rules.{config_name}.yaml`
4. **Default config** - `config/volume_translation_rules.yaml`
5. **Hardcoded defaults** - Fallback values in code

### Named Configurations

**Default Mode** (balanced):
```python
wrapper = VolumeTranslationWrapper()
# max_workers=5, quality_threshold=9.5, strict footnote validation
```

**Strict Mode** (maximum quality):
```python
wrapper = VolumeTranslationWrapper(config_name="strict")
# max_workers=3, quality_threshold=9.8, block_config="strict"
```

**Fast Mode** (speed optimized):
```python
wrapper = VolumeTranslationWrapper(config_name="fast")
# max_workers=10, quality_threshold=8.5, allows footnote mismatches
```

### Work-Specific Overrides

Create `config/volume_work_overrides/D1379_rules.yaml`:

```yaml
parallel:
  max_workers: 8  # D1379 has shorter chapters, use more workers

validation:
  aggregate_quality_threshold: 9.7  # Higher standard for this work

block_config:
  config_name: "strict"  # Use strict mode for individual blocks
```

Then use:

```python
wrapper = VolumeTranslationWrapper(work_id="D1379")
```

### Direct Parameter Overrides

```python
wrapper = VolumeTranslationWrapper(
    max_workers=10,
    aggregate_quality_threshold=9.0,
    block_config_name="fast"
)
```

### Configuration Reference

**Parallel Processing**:
- `max_workers` (int, default: 5) - Concurrent workers (1-50)
- `timeout_per_block` (int, default: 300) - Timeout per block in seconds

**Validation**:
- `aggregate_quality_threshold` (float, default: 9.5) - Minimum average quality (0.0-10.0)
- `allow_footnote_mismatches` (bool, default: false) - Allow footnote inconsistencies
- `block_quality_threshold` (float, default: 9.5) - Individual block quality threshold

**Block Configuration**:
- `block_config_name` (str, optional) - Named config for ContentBlockTranslationWrapper
- `block_quality_threshold_override` (float, optional) - Override block quality
- `block_max_retries` (int, optional) - Override block retries

**Reporting**:
- `include_per_block_stats` (bool, default: true) - Per-block breakdown in manifest
- `include_body_vs_nonbody_breakdown` (bool, default: true) - Separate body/non-body stats
- `save_detailed_manifest` (bool, default: true) - Generate comprehensive manifest

**Logging**:
- `level` (str, default: "INFO") - Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `log_progress` (bool, default: true) - Show progress bar
- `log_statistics` (bool, default: true) - Log statistics after completion

## Usage Examples

### Example 1: Basic Translation

```python
from wrappers import VolumeTranslationWrapper
import json

# Load volume
with open("volume.json", "r") as f:
    volume = json.load(f)

# Translate
wrapper = VolumeTranslationWrapper()
result = wrapper.execute(volume, work_id="D1379")

# Save
if result.success:
    with open("translated.json", "w") as f:
        json.dump(result.translated_volume, f, indent=2, ensure_ascii=False)
```

### Example 2: Multi-Volume Work

```python
# Translate multiple volumes
volumes = ["a", "b", "c"]

for volume_id in volumes:
    # Load volume
    with open(f"volume_{volume_id}.json", "r") as f:
        volume_data = json.load(f)

    # Translate with volume-specific ID
    wrapper = VolumeTranslationWrapper(work_id="I1046")
    result = wrapper.execute(
        volume_data=volume_data,
        work_id="I1046",
        volume_id=volume_id
    )

    # Save
    if result.success:
        with open(f"translated_volume_{volume_id}.json", "w") as f:
            json.dump(result.translated_volume, f, indent=2, ensure_ascii=False)
```

### Example 3: Statistics Analysis

```python
wrapper = VolumeTranslationWrapper()
result = wrapper.execute(volume, work_id="D1379")

# Access statistics
stats = result.statistics

print(f"Total Blocks: {stats.total_blocks}")
print(f"  Body: {stats.body_blocks_count}")
print(f"  Non-Body: {stats.non_body_blocks_count}")
print()
print(f"Quality Metrics:")
print(f"  Overall Average: {stats.average_quality:.2f}")
print(f"  Body Average: {stats.body_avg_quality:.2f}")
print(f"  Non-Body Average: {stats.non_body_avg_quality:.2f}")
print()
print(f"Footnotes:")
print(f"  Total: {stats.total_footnotes}")
print(f"  Body: {stats.body_footnotes}")
print(f"  Non-Body: {stats.non_body_footnotes}")
print(f"  Mismatches: {stats.total_footnote_mismatches}")
print()
print(f"Performance:")
print(f"  Total Time: {stats.total_translation_time:.1f}s")
print(f"  Avg Time/Block: {stats.avg_time_per_block:.1f}s")
print(f"  Success Rate: {stats.success_rate * 100:.1f}%")
```

### Example 4: Custom Validation Handler

```python
wrapper = VolumeTranslationWrapper(
    aggregate_quality_threshold=9.0,
    allow_footnote_mismatches=True
)

result = wrapper.execute(volume, work_id="D1379")

# Custom validation logic
if result.validation_report:
    report = result.validation_report

    if not report.quality_passed:
        print(f"Warning: Quality {report.average_quality:.1f} below threshold")

    if not report.footnote_validation_passed:
        print(f"Warning: {report.total_footnote_mismatches} footnote mismatches")

    if report.quality_failures:
        print(f"Low quality blocks:")
        for failure in report.quality_failures:
            print(f"  - {failure['block_id']}: {failure['quality_score']:.1f}")
```

### Example 5: Integration with Existing Pipeline

```python
# In scripts/orchestrate_translation_pipeline.py

# OLD: Sequential processing
# for block in body_blocks:
#     result = translate_block(block)

# NEW: Parallel volume translation
from wrappers import VolumeTranslationWrapper

wrapper = VolumeTranslationWrapper(
    work_id=work_id,
    max_workers=5,
    block_config_name="strict"
)

result = wrapper.execute(
    volume_data=cleaned_json,
    work_id=work_id,
    volume_id=volume_id
)

if result.success:
    print(f"✓ Volume translation completed")
    print(f"  Average quality: {result.statistics.average_quality:.1f}/10")
    print(f"  Total blocks: {result.statistics.total_blocks}")
    print(f"  Time: {result.statistics.total_translation_time:.1f}s")

    # Save translated volume
    output_path = f"translated_{work_id}.json"
    with open(output_path, "w") as f:
        json.dump(result.translated_volume, f, indent=2, ensure_ascii=False)
else:
    print(f"✗ Volume translation failed")
    print(f"  Errors: {result.validation_report.validation_errors}")
```

## Statistics & Validation

### VolumeStatistics

Comprehensive metrics collected across the entire volume:

```python
@dataclass
class VolumeStatistics:
    # Block counts
    total_blocks: int
    body_blocks_count: int
    non_body_blocks_count: int

    # Success metrics
    successful_blocks: int
    failed_blocks: int
    success_rate: float

    # Quality metrics
    average_quality: float
    min_quality: float
    max_quality: float
    body_avg_quality: float
    non_body_avg_quality: float

    # Footnote metrics
    total_footnotes: int
    total_footnote_mismatches: int
    body_footnotes: int
    non_body_footnotes: int

    # Performance metrics
    total_translation_time: float
    avg_time_per_block: float

    # Character counts
    total_source_chars: int
    total_translated_chars: int
    avg_length_ratio: float

    # Breakdown
    body_block_stats: BlockTypeStats
    non_body_block_stats: BlockTypeStats
```

### AggregateValidationReport

Validation results for the entire volume:

```python
@dataclass
class AggregateValidationReport:
    is_valid: bool  # Overall pass/fail

    # Quality validation
    average_quality: float
    quality_threshold: float
    quality_passed: bool

    # Footnote validation
    total_footnote_mismatches: int
    footnote_validation_passed: bool

    # Block-level failures
    failed_blocks: List[str]  # Block IDs
    quality_failures: List[Dict]
    footnote_failures: List[Dict]

    # Summary
    validation_errors: List[str]
    validation_warnings: List[str]
```

### Validation Rules

1. **Average Quality**: `average_quality >= aggregate_quality_threshold` (default: 9.5)
2. **Footnote Consistency**: `total_footnote_mismatches == 0` (unless `allow_footnote_mismatches=true`)
3. **Block Success**: All blocks must succeed (no failures)

All three conditions must be met for `is_valid=true`.

## Integration with Translation Pipeline

### Current Pipeline (Sequential)

```python
# Stage 4: Body Translation (OLD)
for block in body_blocks:
    result = translate_block(block)
    if not result.success:
        handle_error(result)
    translated_blocks.append(result)
```

**Issues**:
- Slow (sequential processing)
- No aggregate validation
- Limited statistics
- Poor progress visibility

### New Pipeline (Parallel)

```python
# Stage 4: Body Translation (NEW)
from wrappers import VolumeTranslationWrapper

wrapper = VolumeTranslationWrapper(
    work_id=work_id,
    max_workers=5
)

result = wrapper.execute(
    volume_data=cleaned_json,
    work_id=work_id
)

if result.success:
    print(f"✓ Average quality: {result.statistics.average_quality:.1f}")
    print(f"✓ Zero footnote mismatches")
    print(f"✓ {result.statistics.total_blocks} blocks in {result.statistics.total_translation_time:.1f}s")
else:
    print(f"✗ Validation failed: {result.validation_report.validation_errors}")
```

**Benefits**:
- 5-10x faster (parallel processing)
- Aggregate validation ensures quality
- Comprehensive statistics
- Real-time progress tracking

## Performance

### Throughput

With default configuration (`max_workers=5`):

- **Small blocks** (<500 chars): ~200 blocks/hour
- **Medium blocks** (500-2000 chars): ~100 blocks/hour
- **Large blocks** (>2000 chars): ~50 blocks/hour

### Scaling

```python
# Conservative (strict mode)
wrapper = VolumeTranslationWrapper(
    config_name="strict",  # max_workers=3
)

# Balanced (default)
wrapper = VolumeTranslationWrapper()  # max_workers=5

# Aggressive (fast mode)
wrapper = VolumeTranslationWrapper(
    config_name="fast",  # max_workers=10
)

# Custom scaling
wrapper = VolumeTranslationWrapper(
    max_workers=20  # Maximum parallelism
)
```

**Note**: Higher `max_workers` increases:
- Memory usage (each worker loads translation model)
- API rate limit pressure
- Risk of rate limiting errors

### Memory Usage

Approximate memory per worker:
- Base: ~500 MB (Python + dependencies)
- Per worker: ~200 MB (translation model in memory)

Total memory: `500 MB + (max_workers × 200 MB)`

Examples:
- `max_workers=5`: ~1.5 GB
- `max_workers=10`: ~2.5 GB
- `max_workers=20`: ~4.5 GB

## Error Handling

### Block-Level Failures

Individual block failures do NOT stop volume processing:

```python
result = wrapper.execute(volume, work_id="D1379")

# Check for partial failures
if result.statistics.failed_blocks > 0:
    print(f"Warning: {result.statistics.failed_blocks} blocks failed")

    # Identify failed blocks
    for block_result in result.block_results:
        if not block_result.success:
            print(f"  - {block_result.block_id}: {block_result.error_message}")
```

However, **aggregate validation will fail** if any blocks fail.

### Timeout Handling

Per-block timeout prevents hanging:

```python
wrapper = VolumeTranslationWrapper(
    timeout_per_block=600  # 10 minutes max per block
)
```

If a block exceeds timeout, it's marked as failed and processing continues.

### Retry Logic

Retries are handled at the **ContentBlockTranslationWrapper** level:

```python
wrapper = VolumeTranslationWrapper(
    block_max_retries=10  # Override block-level retries
)
```

Each block gets multiple attempts before being marked as failed.

### Validation Failures

If aggregate validation fails:

```python
result = wrapper.execute(volume, work_id="D1379")

if not result.success:
    report = result.validation_report

    # Check specific failure reasons
    if not report.quality_passed:
        print(f"Quality failure: {report.average_quality:.1f} < {report.quality_threshold}")

    if not report.footnote_validation_passed:
        print(f"Footnote mismatch: {report.total_footnote_mismatches} mismatches")

    if report.failed_blocks:
        print(f"Block failures: {len(report.failed_blocks)} blocks failed")
```

## API Reference

### VolumeTranslationWrapper

```python
class VolumeTranslationWrapper:
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

        Args:
            config_path: Explicit path to volume config YAML
            config_name: Named config ("strict", "fast")
            work_id: Work ID for work-specific overrides
            max_workers: Maximum parallel workers
            block_config_path: Config path for ContentBlockTranslationWrapper
            block_config_name: Named config for ContentBlockTranslationWrapper
            **kwargs: Additional overrides
        """

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
            VolumeTranslationResult with translated data and reports
        """
```

### VolumeTranslationResult

```python
@dataclass
class VolumeTranslationResult:
    success: bool  # Overall success/failure

    # Data
    translated_volume: Optional[Dict[str, Any]]

    # Reports
    statistics: VolumeStatistics
    validation_report: Optional[AggregateValidationReport]

    # Details
    block_results: List[BlockResult]
    manifest: Optional[Dict[str, Any]]

    # Error details (if failed)
    error_details: Optional[Dict[str, Any]]
```

### Configuration Files

**Default**: `config/volume_translation_rules.yaml`
**Strict**: `config/volume_translation_rules.strict.yaml`
**Fast**: `config/volume_translation_rules.fast.yaml`
**Work Override**: `config/volume_work_overrides/{work_id}_rules.yaml`

### Metadata

**Node metadata**: `wrappers/volume_translation_wrapper.metadata.json`

### See Also

- [Content Block Translation Wrapper](CONTENT_BLOCK_TRANSLATION_WRAPPER.md) - Block-level translation
- [Translation Configuration](../config/README.md) - Configuration system details
- [Translation Pipeline](../scripts/orchestrate_translation_pipeline.py) - Full 7-stage pipeline

---

**Last Updated**: 2025-11-16
**Version**: 1.0.0
**Status**: Production Ready
