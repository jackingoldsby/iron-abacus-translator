# Workflow Node Wrappers

This directory contains workflow node wrappers that provide clean, workflow-ready interfaces around existing translation utilities.

## Available Wrappers

### 1. Content Block Translation Wrapper (Block-Level)

**File**: `content_block_translation_wrapper.py`
**Metadata**: `content_block_translation_wrapper.metadata.json`
**Documentation**: `../docs/CONTENT_BLOCK_TRANSLATION_WRAPPER.md`

Translates individual content blocks from Classical Chinese to English with:
- **Footnote Marker Validation** (CRITICAL): Ensures markers [1], [2], [3]... match footnotes array
- **Quality Threshold Enforcement**: Minimum quality score of 9.5/10 (configurable)
- **Retry Logic**: 5 attempts by default (configurable)
- **Structured Logging**: JSON logs with detailed metrics
- **Manifest Generation**: Complete processing metadata

**Quick Start**:
```python
from wrappers import ContentBlockTranslationWrapper

wrapper = ContentBlockTranslationWrapper(max_retries=5, quality_threshold=9.5)

result = wrapper.execute(
    content_text_id=42,
    content_source_text="且言紂王只因進香之後，看見女媧美貌。",
    work_id="D1379"
)

if result.success:
    print(f"Quality: {result.validation_report.quality_score:.1f}/10")
    translated = result.translated_data
```

**Key Features**:
- ✅ Footnote validation runs BEFORE quality check (critical ordering)
- ✅ Each retry performs both footnote AND quality validation
- ✅ Configurable retry attempts and quality threshold
- ✅ Comprehensive manifest with processing metadata
- ✅ Detailed error reporting with context
- ✅ Can run standalone or integrated into pipeline

---

### 2. Volume Translation Wrapper (Volume-Level)

**File**: `volume_translation_wrapper.py`
**Metadata**: `volume_translation_wrapper.metadata.json`
**Documentation**: `../docs/VOLUME_TRANSLATION_WRAPPER.md`

Orchestrates parallel translation of entire volumes using fan-out/fan-in pattern with:
- **Parallel Processing**: Process multiple blocks concurrently (5-10x faster)
- **Aggregate Validation**: Average quality >= 9.5, zero footnote mismatches
- **Statistics Breakdown**: Body vs non-body content metrics
- **Progress Tracking**: Real-time progress bars with quality metrics
- **Comprehensive Reporting**: Detailed statistics and validation reports

**Quick Start**:
```python
from wrappers import VolumeTranslationWrapper

wrapper = VolumeTranslationWrapper(max_workers=5)

result = wrapper.execute(
    volume_data=volume_json,
    work_id="D1379"
)

if result.success:
    print(f"Average quality: {result.statistics.average_quality:.1f}/10")
    print(f"Total blocks: {result.statistics.total_blocks}")
    print(f"Time: {result.statistics.total_translation_time:.1f}s")
```

**Key Features**:
- ✅ Fan-out/fan-in parallel processing pattern
- ✅ Aggregate validation across all blocks
- ✅ Statistics breakdown (body vs non-body)
- ✅ Progress visualization with tqdm
- ✅ Configurable workers and quality thresholds
- ✅ Seamless integration with ContentBlockTranslationWrapper

**Configuration Modes**:
- **Default**: 5 workers, quality >= 9.5, strict footnote validation
- **Strict**: 3 workers, quality >= 9.8, uses strict block config
- **Fast**: 10 workers, quality >= 8.5, allows footnote mismatches

**Performance**:
- 100-200 blocks/hour (with 5 workers)
- 5-10x faster than sequential processing
- Scales with max_workers configuration

## Wrapper Architecture

All wrappers follow a consistent pattern:

### Base Interface

```python
class WorkflowNodeWrapper:
    """Base interface for workflow node wrappers"""

    def __init__(self, **config):
        """Initialize with configuration"""
        pass

    def execute(self, **inputs) -> Result:
        """
        Main execution method.

        Returns:
            Result with success status, data, validation, manifest, metrics
        """
        pass

    def _validate_input(self, data) -> ValidationResult:
        """Validate input against schema and business rules"""
        pass

    def _validate_output(self, data) -> ValidationResult:
        """Validate output quality"""
        pass

    def _generate_manifest(self, ...) -> Dict:
        """Generate comprehensive manifest"""
        pass
```

### Standard Result Format

```python
@dataclass
class Result:
    success: bool
    translated_data: Optional[Dict] = None
    validation_report: Optional[ValidationResult] = None
    manifest: Optional[Dict] = None
    metrics: Optional[Dict] = None
    error_details: Optional[Dict] = None
    attempts_used: int = 1
```

## Directory Structure

```
wrappers/
├── __init__.py                                    # Package exports
├── README.md                                      # This file
├── content_block_translation_wrapper.py           # Block-level translation
├── content_block_translation_wrapper.metadata.json # Block wrapper metadata
├── translation_config.py                          # Block config loader
├── volume_translation_wrapper.py                  # Volume-level translation (NEW)
├── volume_translation_wrapper.metadata.json       # Volume wrapper metadata (NEW)
├── volume_config.py                               # Volume config loader (NEW)
└── (future wrappers...)
    ├── metadata_translation_wrapper.py
    ├── toc_translation_wrapper.py
    ├── headings_translation_wrapper.py
    ├── footnote_cleanup_wrapper.py
    └── validation_wrapper.py
```

## Validation Strategy

Wrappers enforce business rules through multi-stage validation:

### 1. Input Validation
- Schema compliance (required fields, types)
- Business rule checks (minimum length, valid IDs)
- **Outcome**: Reject immediately if invalid

### 2. Processing
- Delegate to existing utilities (TranslationService, etc.)
- Handle exceptions gracefully
- **Outcome**: Retry on failure up to max_retries

### 3. Output Validation
- **Critical checks** (e.g., footnote marker consistency)
- **Quality checks** (threshold enforcement)
- **Outcome**: Retry if validation fails

### 4. Manifest Generation
- Track inputs, outputs, metadata
- Record timing, attempts, quality scores
- **Outcome**: Complete audit trail

## Retry Policy

**Standard Retry Configuration**:
- **max_retries**: 5 attempts (configurable)
- **Backoff**: None (immediate retry)
- **Validation on each attempt**: Yes

**Retry Conditions**:
1. Critical validation failures (footnote mismatch, empty output)
2. Quality threshold not met
3. Processing exceptions (API errors, timeouts)

**NOT Retried**:
- Input validation failures (rejected immediately)
- Configuration errors

## Logging

All wrappers use structured logging:

```python
# Info events
logger.info("Wrapper initialized: config=...")
logger.info("Processing started: id=42, work=D1379")
logger.info("Processing successful: quality=9.8/10, attempts=2")

# Warning events
logger.warning("Attempt 1 failed: footnote_marker_mismatch")
logger.warning("Quality below threshold: 9.2 < 9.5")

# Error events
logger.error("Processing failed after 5 attempts")
logger.error("Input validation failed: errors=[...]")
```

## Testing

### Unit Tests

```bash
# Run all wrapper tests
pytest tests/wrappers/ -v

# Run specific wrapper tests
pytest tests/wrappers/test_content_block_translation_wrapper.py -v

# With coverage
pytest tests/wrappers/ --cov=wrappers --cov-report=html
```

### Integration Tests

```bash
# Run integration tests
pytest tests/integration/test_translation_pipeline.py -v
```

### Example Scripts

```bash
# Run examples
python examples/content_block_translation_example.py
```

## Manifest Format

All wrappers generate manifests with this structure:

```json
{
  "node_id": "wrapper_identifier",
  "node_name": "Human-readable name",
  "node_version": "1.0.0",

  "start_time": "ISO 8601 timestamp",
  "end_time": "ISO 8601 timestamp",
  "duration_seconds": 5.2,
  "attempts": 2,

  "input_hash": "hash for tracking",
  "output_hash": "hash for tracking",

  "quality_score": 9.8,
  "quality_threshold": 9.5,
  "validation_passed": true,
  "validation_errors": [],
  "validation_warnings": [],

  "model": "gpt-4.1-nano",
  "configuration": {...}
}
```

## Future Wrappers

Planned wrappers following the same pattern:

1. **Metadata Translation Wrapper** - Translate title, author, publisher (NO footnotes)
2. **TOC Translation Wrapper** - Translate table of contents (NO footnotes)
3. **Headings Translation Wrapper** - Translate chapter headings (NO footnotes)
4. **Special Sections Wrapper** - Translate front/back matter (WITH footnotes)
5. **Footnote Cleanup Wrapper** - Multi-stage footnote processing
6. **Validation Wrapper** - Final quality validation

## Design Principles

1. **Thin Wrappers**: Delegate actual work to existing utilities
2. **Strict Contracts**: Well-defined inputs/outputs with validation
3. **Comprehensive Manifests**: Complete audit trail for all processing
4. **Testable**: Can run standalone, mock dependencies easily
5. **Configurable**: Support different models, thresholds, retry policies
6. **Structured Logging**: JSON logs for analysis and debugging
7. **Error Context**: Detailed error reporting for troubleshooting

## Integration with Pipeline

Wrappers integrate seamlessly with the translation pipeline:

```python
# In scripts/orchestrate_translation_pipeline.py

from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper

# Stage 4: Body Translation
wrapper = ContentBlockTranslationWrapper(
    max_retries=config.max_retries,
    quality_threshold=config.quality_threshold
)

for block in body_blocks:
    result = wrapper.execute(
        content_text_id=block["id"],
        content_source_text=block["content"],
        work_id=work_id
    )

    if result.success:
        block.update(result.translated_data)
        store_manifest(result.manifest)
    else:
        handle_failure(result.error_details)
```

## References

- **CLAUDE.md**: Project architecture and patterns
- **workflow-node-wrapper-builder.md**: Wrapper design specifications
- **docs/CONTENT_BLOCK_TRANSLATION_WRAPPER.md**: Detailed wrapper documentation
- **tests/wrappers/**: Unit tests and examples

## Support

For issues or questions:
1. Check wrapper documentation in `docs/`
2. Review test cases for usage examples
3. Consult metadata files for configuration options
4. See CLAUDE.md for project-wide patterns
