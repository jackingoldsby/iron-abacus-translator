# Content Block Translation Wrapper - Integration Guide

## Overview

The **Content Block Translation Wrapper** is a workflow node that provides a robust, validated interface for translating individual content blocks from Classical Chinese to English with cultural footnotes.

**Key Features**:
- **External Configuration**: YAML-based config files with work-specific overrides
- **Footnote Marker Validation**: Ensures footnote markers in text match footnotes array
- **Quality Threshold Enforcement**: Requires minimum quality score of 9.5/10
- **Retry Logic**: Configurable retry attempts (default: 5)
- **Structured Logging**: JSON logs with detailed metrics
- **Manifest Generation**: Complete processing metadata and audit trail
- **Backward Compatibility**: Existing code works without changes

## Installation

The wrapper is located at:
```
/Users/jacki/PycharmProjects/agentic_test_project/wrappers/content_block_translation_wrapper.py
```

### Dependencies

```python
# Required
from processors.translator import TranslationService
from utils.wuxia_glossary import WuxiaGlossary  # Optional

# External
import openai  # openai>=1.0.0
```

## Usage

### Configuration-Based Usage (Recommended)

```python
from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper

# Use default configuration
wrapper = ContentBlockTranslationWrapper()

# Use named configuration (strict, fast)
wrapper = ContentBlockTranslationWrapper(config_name="strict")

# Use work-specific configuration
wrapper = ContentBlockTranslationWrapper(work_id="D1379")

# Combine work config with overrides
wrapper = ContentBlockTranslationWrapper(
    work_id="D1379",
    max_retries=10  # Override work config
)

# Execute translation
result = wrapper.execute(
    content_text_id=42,
    content_source_text="且言紂王只因進香之後，看見女媧美貌。",
    work_id="D1379"
)

# Check result
if result.success:
    print(f"Quality: {result.validation_report.quality_score:.1f}/10")
    print(f"Footnotes: {result.validation_report.footnote_marker_count}")
    translated_data = result.translated_data
else:
    print(f"Error: {result.error_details}")
    print(f"Attempts: {result.attempts_used}")
```

### Legacy Usage (Backward Compatible)

```python
# Existing code still works without changes
wrapper = ContentBlockTranslationWrapper(
    max_retries=5,
    quality_threshold=9.5
)

# Full legacy parameters
wrapper = ContentBlockTranslationWrapper(
    model="gpt-4o",
    temperature=0.5,
    max_retries=10,
    quality_threshold=8.0,
    timeout=180,
    glossary_path=Path("./wuxia_glossary.db")
)
```

## Configuration Files

### Configuration Priority

Configuration is loaded in this priority order (highest to lowest):

1. **Direct kwargs parameters** - Backward compatibility
2. **Work-specific override** - `config/work_overrides/{work_id}_rules.yaml`
3. **Named config** - `config/translation_rules.{config_name}.yaml`
4. **Default config** - `config/translation_rules.yaml`
5. **Hardcoded defaults** - Fallback if no config files

### Available Configurations

**Default** (`config/translation_rules.yaml`):
- Quality threshold: 9.5
- Max retries: 5
- Backoff strategy: exponential

**Strict** (`config/translation_rules.strict.yaml`):
- Quality threshold: 9.8 (higher)
- Max retries: 3 (fewer)
- Temperature: 0.2 (lower for consistency)
- Logging: DEBUG level

**Fast** (`config/translation_rules.fast.yaml`):
- Quality threshold: 8.5 (lower)
- Max retries: 2 (fewer)
- Temperature: 0.4 (higher)
- Logging: WARNING level

### Work-Specific Overrides

Create `config/work_overrides/{work_id}_rules.yaml` for work-specific settings:

```yaml
# config/work_overrides/D1379_rules.yaml
validation:
  quality:
    threshold: 9.7

retry:
  max_attempts: 7

translation:
  temperature: 0.25

glossary:
  enabled: true
  path: "/path/to/martial_arts_glossary.db"

logging:
  level: "DEBUG"
```

### Custom Configuration File

```python
# Load from explicit path
wrapper = ContentBlockTranslationWrapper(
    config_path="/path/to/custom_config.yaml"
)
```

## Workflow Integration

### Integration with Translation Pipeline

```python
# In scripts/orchestrate_translation_pipeline.py

from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper

def translate_body_blocks(
    data: Dict[str, Any],
    config: TranslationConfig,
    work_id: str
) -> Dict[str, Any]:
    """Translate all body content blocks with validation"""

    # Initialize wrapper
    wrapper = ContentBlockTranslationWrapper(
        model=config.model,
        max_retries=config.max_retries,
        quality_threshold=config.quality_threshold
    )

    # Get chapters
    chapters = data["structure"]["body"]["chapters"]

    # Translate each block
    for chapter in chapters:
        for block in chapter["content_blocks"]:
            result = wrapper.execute(
                content_text_id=block["id"],
                content_source_text=block["content"],
                work_id=work_id
            )

            if result.success:
                # Update block with translation
                block["translated_content"] = result.translated_data[
                    "translated_annotated_content"]["annotated_content_text"
                ]
                block["footnotes"] = result.translated_data[
                    "translated_annotated_content"]["content_footnotes"
                ]
                block["content_type"] = result.translated_data[
                    "translated_annotated_content"]["content_type"
                ]

                # Store manifest
                store_manifest(work_id, block["id"], result.manifest)
            else:
                # Handle failure
                log_translation_failure(work_id, block["id"], result.error_details)
                raise TranslationError(f"Block {block['id']} failed: {result.error_details}")

    return data
```

### Parallel Processing

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def translate_blocks_parallel(blocks: List[Dict], wrapper: ContentBlockTranslationWrapper, work_id: str):
    """Translate multiple blocks in parallel"""

    results = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(
                wrapper.execute,
                block["id"],
                block["content"],
                work_id
            ): block
            for block in blocks
        }

        for future in as_completed(futures):
            block = futures[future]
            try:
                result = future.result()
                results.append((block, result))
            except Exception as e:
                logger.error(f"Block {block['id']} raised exception: {e}")

    return results
```

## Validation Details

### Footnote Marker Validation

**CRITICAL**: This validation runs BEFORE quality check.

**Validation Logic**:
1. Extract all `[N]` markers from translated text
2. Count unique markers (e.g., `[1]`, `[2]`, `[3]` → count = 3)
3. Count footnotes in `content_footnotes` array
4. **FAIL** if counts don't match
5. **FAIL** if markers not sequential (e.g., `[1]`, `[3]` missing `[2]`)

**Example Failure**:
```python
# Translation has 3 markers: [1], [2], [3]
translated_text = "King Zhou[1] visited Nüwa[2] and saw beauty[3]."

# But only 2 footnotes in array
footnotes = [
    {"footnote_key": 1, "details": {...}},
    {"footnote_key": 2, "details": {...}}
]

# Result: FAIL - marker count (3) != footnote count (2)
# Action: Retry translation
```

### Quality Threshold Validation

**Quality Score Calculation** (0-10 scale):
- Start: 10.0
- **-3.0** for each critical error (empty translation, identical to source)
- **-0.5** for each warning (suspicious length ratio, invalid content type)
- Minimum: 0.0

**Validation Checks**:
1. Translation not empty
2. Translation different from source
3. Length ratio between 0.5 and 3.0 (50% to 300% of source)
4. Valid content type (narrative, dialogue, verse, document, descriptive, thought)
5. Quality score >= threshold (default 9.5)

**Example Failure**:
```python
# Translation quality score: 9.2
# Threshold: 9.5
# Result: FAIL - quality below threshold
# Action: Retry translation
```

## Retry Policy

**Default Configuration**:
- **max_retries**: 5 attempts
- **Backoff**: None (immediate retry)
- **Validation**: Both footnote and quality checks on each attempt

**Retry Conditions**:
1. Footnote marker mismatch
2. Quality threshold not met
3. Translation exception (API error, timeout, etc.)

**Retry Flow**:
```
Attempt 1:
  → Translate
  → Validate footnotes (FAIL: mismatch)
  → Retry

Attempt 2:
  → Translate
  → Validate footnotes (PASS)
  → Validate quality (FAIL: score 9.2 < 9.5)
  → Retry

Attempt 3:
  → Translate
  → Validate footnotes (PASS)
  → Validate quality (PASS: score 9.8)
  → SUCCESS
```

## Error Handling

### Input Validation Failure
```python
result = wrapper.execute(
    content_text_id=None,  # Invalid
    content_source_text=""
)

# result.success = False
# result.error_details = {
#     "validation_errors": [
#         "content_text_id is required",
#         "content_source_text is empty"
#     ]
# }
# result.attempts_used = 0  # No translation attempted
```

### All Retries Exhausted
```python
result = wrapper.execute(
    content_text_id=1,
    content_source_text="Source text"
)

# After 5 failed attempts:
# result.success = False
# result.error_details = {
#     "message": "Failed after 5 attempts",
#     "last_error": {
#         "attempt": 5,
#         "error_type": "footnote_marker_mismatch",
#         "details": ["Footnote marker mismatch: 3 markers but 2 footnotes"]
#     },
#     "attempts_used": 5
# }
```

## Manifest Structure

The wrapper generates a comprehensive manifest for each translation:

```json
{
  "node_id": "content_block_translation_node",
  "node_name": "Content Block Translation",
  "node_version": "1.0.0",
  "content_text_id": 42,
  "work_id": "D1379",

  "start_time": "2025-11-16T10:30:00",
  "end_time": "2025-11-16T10:30:05",
  "duration_seconds": 5.2,
  "attempts": 2,

  "input_hash": "a1b2c3d4e5f6g7h8",
  "input_char_count": 45,

  "output_hash": "h8g7f6e5d4c3b2a1",
  "output_char_count": 120,
  "footnote_count": 3,
  "content_type": "narrative",

  "quality_score": 9.8,
  "quality_threshold": 9.5,
  "validation_passed": true,
  "validation_errors": [],
  "validation_warnings": [],

  "model": "gpt-4.1-nano",
  "temperature": 0.3,
  "max_retries": 5
}
```

## Logging

### Log Events

The wrapper logs the following events:

```python
# Initialization
logger.info("Initialized Content Block Translation wrapper: model=gpt-4.1-nano, ...")

# Translation start
logger.info("Starting translation for content_text_id=42, work_id=D1379, length=45 chars")

# Attempt start
logger.info("Translation attempt 1/5")

# Validation failures
logger.warning("Attempt 1: Footnote validation failed - [...errors...]")
logger.warning("Attempt 2: Quality validation failed - score 9.2 < threshold 9.5")

# Success
logger.info("Translation successful on attempt 3: quality=9.8/10, footnotes=3")

# Final failure
logger.error("Translation failed after 5 attempts for content_text_id=42")
```

### Structured Logging Example

```python
import logging
import json

# Configure structured JSON logging
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        return json.dumps(log_data)

handler = logging.FileHandler("translation.json")
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
```

## Testing

### Running Unit Tests

```bash
# Run all wrapper tests
pytest tests/wrappers/test_content_block_translation_wrapper.py -v

# Run specific test class
pytest tests/wrappers/test_content_block_translation_wrapper.py::TestFootnoteMarkerValidator -v

# Run with coverage
pytest tests/wrappers/test_content_block_translation_wrapper.py --cov=wrappers --cov-report=html
```

### Test Coverage

Current test coverage: **~85%**

**Covered**:
- Input validation
- Footnote marker validation
- Quality validation
- Retry logic
- Manifest generation
- Error handling

**Not Covered**:
- Actual OpenAI API calls (mocked)
- Network failures
- Timeout scenarios

## Performance Characteristics

**Typical Duration**:
- Small block (<100 chars): 2-3 seconds
- Medium block (100-500 chars): 5-8 seconds
- Large block (>500 chars): 10-15 seconds

**Factors Affecting Duration**:
- OpenAI API response time
- Number of retry attempts
- Text length and complexity
- Footnote count

**Recommendations**:
- Use parallel processing for multiple blocks
- Monitor API rate limits
- Set appropriate timeout values
- Log slow translations for analysis

## Troubleshooting

### Problem: Translations always fail footnote validation

**Symptom**: Every translation attempt fails with "Footnote marker mismatch"

**Possible Causes**:
1. OpenAI model not inserting markers correctly
2. System prompt not being followed
3. JSON parsing issues with markers

**Solutions**:
1. Check TranslationService system prompt includes marker instructions
2. Verify model supports structured output (JSON mode)
3. Increase max_retries to give model more chances
4. Check logs for actual translated text vs expected

### Problem: Quality score always below threshold

**Symptom**: Translations fail quality check despite looking correct

**Possible Causes**:
1. Threshold too high (9.5 is very strict)
2. Warnings accumulating and reducing score
3. Length ratio outside expected range

**Solutions**:
1. Lower quality_threshold to 8.5 or 9.0
2. Review validation warnings in logs
3. Adjust length ratio checks if needed
4. Check if content_type classification is working

### Problem: Wrapper hangs or times out

**Symptom**: No response from wrapper after long wait

**Possible Causes**:
1. OpenAI API timeout
2. Network issues
3. Very long source text

**Solutions**:
1. Increase timeout parameter (default 120s)
2. Check network connectivity
3. Split very long texts into smaller blocks
4. Enable debug logging to see where it hangs

## Best Practices

1. **Always check result.success** before using translated_data
2. **Log manifests** for audit trail and debugging
3. **Monitor attempts_used** to identify problematic blocks
4. **Use parallel processing** for batch translations
5. **Set reasonable thresholds** (9.5 is very high, 9.0 may be more practical)
6. **Review validation warnings** to improve translation quality
7. **Store error_details** for failed translations for analysis

## Metadata Reference

See: `/Users/jacki/PycharmProjects/agentic_test_project/wrappers/content_block_translation_wrapper.metadata.json`

Complete metadata includes:
- Input/output schemas
- Configuration options
- Validation rules
- Business rules
- Usage examples
- Integration points

## Support

For issues or questions:
1. Check logs for detailed error messages
2. Review test cases for usage examples
3. Consult CLAUDE.md for project architecture
4. See workflow-node-wrapper-builder agent for wrapper patterns
