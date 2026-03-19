# Translation Configuration Files

This directory contains YAML configuration files for the ContentBlockTranslationWrapper.

## Structure

```
config/
├── translation_rules.yaml          # Default configuration
├── translation_rules.strict.yaml   # Strict mode (higher quality)
├── translation_rules.fast.yaml     # Fast mode (lower quality, faster)
└── work_overrides/                 # Work-specific configurations
    ├── D1379_rules.yaml            # Config for work D1379
    └── wuxia_classical_rules.yaml  # Generic classical wuxia config
```

## Configuration Priority

When loading configuration, files are merged in this order (highest to lowest priority):

1. **Direct kwargs parameters** - `ContentBlockTranslationWrapper(max_retries=10)`
2. **Work-specific override** - `config/work_overrides/{work_id}_rules.yaml`
3. **Named config** - `config/translation_rules.{config_name}.yaml`
4. **Default config** - `config/translation_rules.yaml`
5. **Hardcoded defaults** - Fallback in code

## Usage Examples

### Use Default Config
```python
from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper

wrapper = ContentBlockTranslationWrapper()
# Loads: config/translation_rules.yaml
```

### Use Named Config
```python
wrapper = ContentBlockTranslationWrapper(config_name="strict")
# Loads: config/translation_rules.strict.yaml

wrapper = ContentBlockTranslationWrapper(config_name="fast")
# Loads: config/translation_rules.fast.yaml
```

### Use Work-Specific Config
```python
wrapper = ContentBlockTranslationWrapper(work_id="D1379")
# Loads: config/translation_rules.yaml (base)
# Then merges: config/work_overrides/D1379_rules.yaml
```

### Override Config Values
```python
wrapper = ContentBlockTranslationWrapper(
    work_id="D1379",
    max_retries=15  # Override work config
)
# Loads D1379 config, but uses 15 retries instead of config value
```

## Configuration Schema

### Validation Section
```yaml
validation:
  quality:
    threshold: 9.5      # Quality threshold (0-10)
    enabled: true       # Enable quality validation

  footnote_markers:
    enabled: true       # Validate footnote markers
    fail_on_mismatch: true
    allowed_patterns:
      - '\[\d+\]'       # Regex patterns for markers

  input:
    min_text_length: 5
    max_text_length: 10000
```

### Retry Section
```yaml
retry:
  max_attempts: 5                    # 1-20 attempts
  backoff_strategy: "exponential"    # exponential, linear, constant
  initial_delay: 1.0                 # seconds
  max_delay: 30.0                    # seconds
  exponential_base: 2.0              # base for exponential backoff
```

### Translation Section
```yaml
translation:
  model: "gpt-4.1-nano"     # OpenAI model
  temperature: 0.3          # 0.0-1.0
  timeout: 120              # seconds
  max_tokens: null          # null = no limit
```

### Formatting Section
```yaml
formatting:
  preserve_whitespace: true
  normalize_quotes: false
  trim_output: true
```

### Logging Section
```yaml
logging:
  level: "INFO"                     # DEBUG, INFO, WARNING, ERROR, CRITICAL
  include_metrics: true
  log_validation_details: true
  log_retry_attempts: true
```

### Glossary Section
```yaml
glossary:
  enabled: false
  path: null                        # Path to glossary database
```

## Named Configurations

### Default (`translation_rules.yaml`)
- Balanced settings for general use
- Quality threshold: 9.5
- Max retries: 5
- Exponential backoff

### Strict (`translation_rules.strict.yaml`)
- Highest quality requirements
- Quality threshold: 9.8
- Max retries: 3
- Lower temperature (0.2)
- DEBUG logging

### Fast (`translation_rules.fast.yaml`)
- Speed over quality
- Quality threshold: 8.5
- Max retries: 2
- Higher temperature (0.4)
- WARNING logging only

## Creating Work-Specific Overrides

### 1. Identify Work Requirements

For work D1379 (martial arts novel):
- Higher quality needed
- More retries for complex terms
- Special glossary required

### 2. Create Override File

Create `config/work_overrides/D1379_rules.yaml`:

```yaml
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

### 3. Use in Code

```python
wrapper = ContentBlockTranslationWrapper(work_id="D1379")
# Automatically loads D1379-specific config
```

## Validation

All configurations are validated using Pydantic schemas. Invalid configurations will raise detailed errors:

```python
# Test config validity
from wrappers.translation_config import TranslationConfig

try:
    config = TranslationConfig.load(config_name="strict")
    print("Config valid!")
except Exception as e:
    print(f"Config invalid: {e}")
```

## Testing

Test config loading:

```bash
# Test default config
python -m wrappers.translation_config

# Run config tests
pytest tests/wrappers/test_content_block_translation_wrapper.py::TestConfigurationLoading -v
```

## Best Practices

1. **Keep default config simple** - Should work for most cases
2. **Use work overrides sparingly** - Only for works with special requirements
3. **Version control configs** - Track changes to configuration
4. **Document work configs** - Add comments explaining why overrides are needed
5. **Test after changes** - Run tests to verify config validity

## Troubleshooting

### Config file not found
Config files are optional. If not found, hardcoded defaults are used.

### Invalid YAML syntax
```bash
# Validate YAML
python -c "import yaml; yaml.safe_load(open('config/translation_rules.yaml'))"
```

### Unknown config parameter
Check parameter names against schema in `wrappers/translation_config.py`.

### Config not taking effect
Check priority order - direct parameters override config files.

## See Also

- [Content Block Translation Wrapper Documentation](../docs/CONTENT_BLOCK_TRANSLATION_WRAPPER.md)
- [Migration Guide](../docs/MIGRATION_GUIDE_CONFIG.md)
- [Wrapper Metadata](../wrappers/content_block_translation_wrapper.metadata.json)
