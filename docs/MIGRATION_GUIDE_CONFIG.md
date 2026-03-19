# Migration Guide: Config File Refactoring

## Overview

The ContentBlockTranslationWrapper has been refactored to support external YAML configuration files while maintaining **100% backward compatibility** with existing code.

**Version**: 1.0.0 → 2.0.0

**Changes**:
- Added YAML-based configuration system
- Added work-specific configuration overrides
- Added named configurations (strict, fast)
- Maintained all existing parameters and behavior

## Do I Need to Migrate?

**NO** - Existing code continues to work without any changes.

**However**, you may want to migrate to config files if:
- You're translating multiple works with different requirements
- You want centralized configuration management
- You need environment-specific settings (dev, staging, production)
- You want to share configuration across multiple translation jobs

## Backward Compatibility

### All Existing Code Works

```python
# This code works exactly as before
wrapper = ContentBlockTranslationWrapper(
    max_retries=5,
    quality_threshold=9.5
)
```

No changes required to existing code.

## Migration Scenarios

### Scenario 1: Single Work Translation

**Before** (still works):
```python
wrapper = ContentBlockTranslationWrapper(
    max_retries=5,
    quality_threshold=9.5,
    model="gpt-4.1-nano",
    temperature=0.3
)

for block in blocks:
    result = wrapper.execute(
        content_text_id=block["id"],
        content_source_text=block["content"]
    )
```

**After** (recommended):
```python
# Use default config (same values as before)
wrapper = ContentBlockTranslationWrapper()

for block in blocks:
    result = wrapper.execute(
        content_text_id=block["id"],
        content_source_text=block["content"]
    )
```

**Benefits**:
- Simpler initialization
- Configuration externalized
- Easy to adjust settings without code changes

### Scenario 2: Multiple Works with Different Requirements

**Before**:
```python
# Hard-coded settings for each work
if work_id == "D1379":
    wrapper = ContentBlockTranslationWrapper(
        max_retries=7,
        quality_threshold=9.7,
        temperature=0.25,
        glossary_path="/path/to/martial_arts_glossary.db"
    )
elif work_id == "I1046":
    wrapper = ContentBlockTranslationWrapper(
        max_retries=5,
        quality_threshold=9.5
    )
else:
    wrapper = ContentBlockTranslationWrapper()
```

**After**:
```python
# Automatic config loading based on work_id
wrapper = ContentBlockTranslationWrapper(work_id=work_id)
```

**Benefits**:
- No conditional logic needed
- Work-specific settings in separate files
- Easy to add new works (just create config file)

### Scenario 3: Quality Modes

**Before**:
```python
if strict_mode:
    wrapper = ContentBlockTranslationWrapper(
        max_retries=3,
        quality_threshold=9.8,
        temperature=0.2
    )
elif fast_mode:
    wrapper = ContentBlockTranslationWrapper(
        max_retries=2,
        quality_threshold=8.5,
        temperature=0.4
    )
else:
    wrapper = ContentBlockTranslationWrapper()
```

**After**:
```python
mode = "strict" if strict_mode else "fast" if fast_mode else None
wrapper = ContentBlockTranslationWrapper(config_name=mode)
```

**Benefits**:
- Named configurations
- Consistent settings across codebase
- Easy to add new modes

### Scenario 4: Override Work Config

**New Capability**:
```python
# Use D1379 config but override max_retries
wrapper = ContentBlockTranslationWrapper(
    work_id="D1379",
    max_retries=15  # Override work config's 7 retries
)
```

This combines work-specific settings with runtime overrides.

## Creating Configuration Files

### Step 1: Identify Your Settings

Review your current code:
```python
wrapper = ContentBlockTranslationWrapper(
    max_retries=7,
    quality_threshold=9.7,
    model="gpt-4.1-nano",
    temperature=0.25,
    glossary_path="/path/to/glossary.db"
)
```

### Step 2: Create Work-Specific Config

Create `config/work_overrides/D1379_rules.yaml`:
```yaml
validation:
  quality:
    threshold: 9.7

retry:
  max_attempts: 7

translation:
  model: "gpt-4.1-nano"
  temperature: 0.25

glossary:
  enabled: true
  path: "/path/to/glossary.db"

logging:
  level: "INFO"
```

### Step 3: Update Code

Replace:
```python
wrapper = ContentBlockTranslationWrapper(
    max_retries=7,
    quality_threshold=9.7,
    model="gpt-4.1-nano",
    temperature=0.25,
    glossary_path="/path/to/glossary.db"
)
```

With:
```python
wrapper = ContentBlockTranslationWrapper(work_id="D1379")
```

## Configuration File Template

### Work-Specific Override Template

```yaml
# config/work_overrides/{work_id}_rules.yaml

# Validation settings
validation:
  quality:
    threshold: 9.5  # 0-10 scale
    enabled: true

  footnote_markers:
    enabled: true
    fail_on_mismatch: true

  input:
    min_text_length: 5
    max_text_length: 10000

# Retry settings
retry:
  max_attempts: 5  # 1-20
  backoff_strategy: "exponential"  # exponential, linear, constant
  initial_delay: 1.0  # seconds
  max_delay: 30.0
  exponential_base: 2.0

# Translation settings
translation:
  model: "gpt-4.1-nano"
  temperature: 0.3  # 0.0-1.0
  timeout: 120  # seconds
  max_tokens: null  # null = no limit

# Glossary settings
glossary:
  enabled: false
  path: null  # Path to glossary database

# Logging settings
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  include_metrics: true
  log_validation_details: true
  log_retry_attempts: true
```

## Testing Your Migration

### 1. Test Backward Compatibility

```python
# Existing code should work unchanged
wrapper = ContentBlockTranslationWrapper(
    max_retries=5,
    quality_threshold=9.5
)

assert wrapper.max_retries == 5
assert wrapper.quality_threshold == 9.5
```

### 2. Test Config Loading

```python
# Test named config
wrapper = ContentBlockTranslationWrapper(config_name="strict")
assert wrapper.quality_threshold == 9.8
assert wrapper.max_retries == 3

# Test work override
wrapper = ContentBlockTranslationWrapper(work_id="D1379")
assert wrapper.quality_threshold == 9.7
assert wrapper.max_retries == 7
```

### 3. Test Override Priority

```python
# Direct params override config
wrapper = ContentBlockTranslationWrapper(
    config_name="strict",
    max_retries=10
)
assert wrapper.max_retries == 10  # Direct param wins
assert wrapper.quality_threshold == 9.8  # From strict config
```

## Common Issues

### Issue: Config file not found

**Error**: `FileNotFoundError: config/translation_rules.yaml`

**Solution**: Config files are optional. If not found, hardcoded defaults are used. Either:
1. Create the config file
2. Don't worry - defaults will be used
3. Pass direct parameters

### Issue: Invalid YAML syntax

**Error**: `ValueError: Invalid YAML file`

**Solution**: Validate YAML syntax:
```bash
python -c "import yaml; yaml.safe_load(open('config/translation_rules.yaml'))"
```

### Issue: Unknown config parameter

**Error**: `ValidationError: Extra inputs are not permitted`

**Solution**: Check parameter names against template. Pydantic validates all fields.

## Rollback Plan

If issues arise, rollback is simple:

```python
# Just pass direct parameters (original way)
wrapper = ContentBlockTranslationWrapper(
    max_retries=5,
    quality_threshold=9.5,
    model="gpt-4.1-nano",
    temperature=0.3
)
```

No code changes needed - backward compatibility is maintained.

## Best Practices

### 1. Use Work-Specific Configs for Complex Works

Create `config/work_overrides/{work_id}_rules.yaml` for:
- Works with special glossaries
- Works requiring higher quality thresholds
- Works with unusual retry requirements

### 2. Use Named Configs for Quality Modes

Use `config_name="strict"` or `config_name="fast"` for:
- Different quality/speed tradeoffs
- Testing vs production
- Batch processing vs interactive

### 3. Use Direct Parameters for One-Off Overrides

```python
wrapper = ContentBlockTranslationWrapper(
    work_id="D1379",
    max_retries=20  # Special case override
)
```

### 4. Keep Default Config Simple

The default config should work for most works. Only create overrides for special cases.

### 5. Version Control Config Files

Add config files to git:
```bash
git add config/
git commit -m "Add translation configuration files"
```

## Questions?

- Check `/Users/jacki/PycharmProjects/agentic_test_project/docs/CONTENT_BLOCK_TRANSLATION_WRAPPER.md`
- Review config examples in `config/` directory
- Run tests: `pytest tests/wrappers/test_content_block_translation_wrapper.py -v`
- See metadata: `wrappers/content_block_translation_wrapper.metadata.json`
