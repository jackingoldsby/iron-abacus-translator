#!/usr/bin/env python3
"""
Translation Configuration Loader

Load and validate translation configuration from YAML files with Pydantic.

Configuration Priority (highest to lowest):
1. Direct kwargs parameters (backward compatibility)
2. Work-specific override file (config/work_overrides/{work_id}_rules.yaml)
3. Named config (config/translation_rules.{config_name}.yaml)
4. Default config (config/translation_rules.yaml)
5. Hardcoded defaults (fallback if no config file)
"""

import sys
import yaml
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

logger = logging.getLogger(__name__)


# =============================================================================
# PYDANTIC MODELS FOR CONFIG VALIDATION
# =============================================================================

class QualityValidationConfig(BaseModel):
    """Quality validation configuration"""
    threshold: float = Field(default=9.5, ge=0.0, le=10.0)
    enabled: bool = True


class FootnoteMarkersConfig(BaseModel):
    """Footnote marker validation configuration"""
    enabled: bool = True
    fail_on_mismatch: bool = True
    allowed_patterns: List[str] = Field(default_factory=lambda: [r'\[\d+\]'])


class InputValidationConfig(BaseModel):
    """Input validation configuration"""
    min_text_length: int = Field(default=5, ge=1)
    max_text_length: int = Field(default=10000, ge=1)


class ValidationConfig(BaseModel):
    """Validation configuration"""
    quality: QualityValidationConfig = Field(default_factory=QualityValidationConfig)
    footnote_markers: FootnoteMarkersConfig = Field(default_factory=FootnoteMarkersConfig)
    input: InputValidationConfig = Field(default_factory=InputValidationConfig)


class RetryConfig(BaseModel):
    """Retry configuration"""
    max_attempts: int = Field(default=5, ge=1, le=20)
    backoff_strategy: str = Field(default="exponential")
    initial_delay: float = Field(default=1.0, ge=0.0)
    max_delay: float = Field(default=30.0, ge=0.0)
    exponential_base: float = Field(default=2.0, ge=1.0)

    @field_validator('backoff_strategy')
    @classmethod
    def validate_backoff_strategy(cls, v: str) -> str:
        allowed = ['exponential', 'linear', 'constant']
        if v not in allowed:
            raise ValueError(f"backoff_strategy must be one of {allowed}, got: {v}")
        return v


class FormattingConfig(BaseModel):
    """Formatting configuration"""
    preserve_whitespace: bool = True
    normalize_quotes: bool = False
    trim_output: bool = True


class TranslationServiceConfig(BaseModel):
    """Translation service configuration"""
    model: str = "gpt-4.1-nano"
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    timeout: int = Field(default=120, ge=1)
    max_tokens: Optional[int] = None


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = "INFO"
    include_metrics: bool = True
    log_validation_details: bool = True
    log_retry_attempts: bool = True

    @field_validator('level')
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"level must be one of {allowed}, got: {v}")
        return v_upper


class GlossaryConfig(BaseModel):
    """Glossary configuration"""
    enabled: bool = False
    path: Optional[str] = None


class TranslationConfig(BaseModel):
    """Complete translation configuration"""
    model_config = ConfigDict(extra='forbid')  # Reject unknown fields

    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    formatting: FormattingConfig = Field(default_factory=FormattingConfig)
    translation: TranslationServiceConfig = Field(default_factory=TranslationServiceConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    glossary: GlossaryConfig = Field(default_factory=GlossaryConfig)

    @classmethod
    def load(
        cls,
        config_path: Optional[str] = None,
        config_name: Optional[str] = None,
        work_id: Optional[str] = None,
        **overrides
    ) -> "TranslationConfig":
        """
        Load configuration with priority system.

        Priority (highest to lowest):
        1. Direct kwargs parameters (overrides)
        2. Work-specific override file (config/work_overrides/{work_id}_rules.yaml)
        3. Named config (config/translation_rules.{config_name}.yaml)
        4. Default config (config/translation_rules.yaml)
        5. Hardcoded defaults

        Args:
            config_path: Explicit path to config file (overrides config_name)
            config_name: Named config (e.g., "strict", "fast")
            work_id: Work ID for work-specific overrides
            **overrides: Direct parameter overrides (backward compatibility)

        Returns:
            TranslationConfig instance

        Example:
            # Use default config
            config = TranslationConfig.load()

            # Use named config
            config = TranslationConfig.load(config_name="strict")

            # Use work-specific override
            config = TranslationConfig.load(work_id="D1379")

            # Direct overrides (backward compatibility)
            config = TranslationConfig.load(max_retries=10, quality_threshold=8.5)

            # Combination: work override + direct override
            config = TranslationConfig.load(work_id="D1379", max_retries=10)
        """
        # Start with hardcoded defaults
        config_dict = cls._get_default_dict()

        # Load base config
        base_config_path = cls._resolve_config_path(config_path, config_name)
        if base_config_path and base_config_path.exists():
            logger.info(f"Loading base config from: {base_config_path}")
            base_dict = cls._load_yaml(base_config_path)
            config_dict = cls._deep_merge(config_dict, base_dict)
        else:
            logger.info("Using hardcoded default configuration")

        # Apply work-specific overrides
        if work_id:
            work_override_path = cls._get_work_override_path(work_id)
            if work_override_path.exists():
                logger.info(f"Applying work-specific overrides from: {work_override_path}")
                work_dict = cls._load_yaml(work_override_path)
                config_dict = cls._deep_merge(config_dict, work_dict)
            else:
                logger.debug(f"No work-specific override found for work_id={work_id}")

        # Apply direct overrides (backward compatibility)
        if overrides:
            logger.info(f"Applying direct parameter overrides: {list(overrides.keys())}")
            override_dict = cls._convert_legacy_overrides(overrides)
            config_dict = cls._deep_merge(config_dict, override_dict)

        # Validate and create config
        try:
            config = cls(**config_dict)
            logger.info("Configuration loaded and validated successfully")
            return config
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            raise

    @staticmethod
    def _get_default_dict() -> Dict[str, Any]:
        """Get hardcoded default configuration"""
        return {
            "validation": {
                "quality": {"threshold": 9.5, "enabled": True},
                "footnote_markers": {
                    "enabled": True,
                    "fail_on_mismatch": True,
                    "allowed_patterns": [r'\[\d+\]']
                },
                "input": {"min_text_length": 5, "max_text_length": 10000}
            },
            "retry": {
                "max_attempts": 5,
                "backoff_strategy": "exponential",
                "initial_delay": 1.0,
                "max_delay": 30.0,
                "exponential_base": 2.0
            },
            "formatting": {
                "preserve_whitespace": True,
                "normalize_quotes": False,
                "trim_output": True
            },
            "translation": {
                "model": "gpt-4.1-nano",
                "temperature": 0.3,
                "timeout": 120,
                "max_tokens": None
            },
            "logging": {
                "level": "INFO",
                "include_metrics": True,
                "log_validation_details": True,
                "log_retry_attempts": True
            },
            "glossary": {
                "enabled": False,
                "path": None
            }
        }

    @staticmethod
    def _resolve_config_path(
        config_path: Optional[str],
        config_name: Optional[str]
    ) -> Optional[Path]:
        """Resolve configuration file path"""
        if config_path:
            return Path(config_path)

        # Find config directory (relative to this file)
        config_dir = Path(__file__).parent.parent / "config"

        if config_name:
            # Named config: config/translation_rules.{name}.yaml
            return config_dir / f"translation_rules.{config_name}.yaml"
        else:
            # Default config: config/translation_rules.yaml
            return config_dir / "translation_rules.yaml"

    @staticmethod
    def _get_work_override_path(work_id: str) -> Path:
        """Get path to work-specific override file"""
        config_dir = Path(__file__).parent.parent / "config" / "work_overrides"
        return config_dir / f"{work_id}_rules.yaml"

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        """Load YAML file"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data if data else {}
        except Exception as e:
            logger.error(f"Failed to load YAML from {path}: {e}")
            raise ValueError(f"Invalid YAML file: {path}") from e

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries"""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Recursively merge nested dicts
                result[key] = TranslationConfig._deep_merge(result[key], value)
            else:
                # Override value
                result[key] = value

        return result

    @staticmethod
    def _convert_legacy_overrides(overrides: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert legacy parameter names to new config structure.

        Legacy parameters (backward compatibility):
        - max_retries -> retry.max_attempts
        - quality_threshold -> validation.quality.threshold
        - model -> translation.model
        - temperature -> translation.temperature
        - timeout -> translation.timeout
        - glossary_path -> glossary.path (and sets glossary.enabled=True)
        """
        config_dict: Dict[str, Any] = {
            "validation": {},
            "retry": {},
            "translation": {},
            "glossary": {}
        }

        # Map legacy parameter names
        legacy_mappings = {
            'max_retries': ('retry', 'max_attempts'),
            'quality_threshold': ('validation', 'quality', 'threshold'),
            'model': ('translation', 'model'),
            'temperature': ('translation', 'temperature'),
            'timeout': ('translation', 'timeout'),
        }

        for legacy_key, value in overrides.items():
            if legacy_key in legacy_mappings:
                path = legacy_mappings[legacy_key]
                TranslationConfig._set_nested(config_dict, path, value)
            elif legacy_key == 'glossary_path':
                config_dict['glossary']['path'] = value
                config_dict['glossary']['enabled'] = True
            else:
                # Unknown parameter - let Pydantic validation handle it
                logger.warning(f"Unknown legacy parameter: {legacy_key}")

        # Remove empty dicts
        return {k: v for k, v in config_dict.items() if v}

    @staticmethod
    def _set_nested(config_dict: Dict[str, Any], path: tuple, value: Any):
        """Set nested dictionary value by path"""
        d = config_dict
        for key in path[:-1]:
            if key not in d:
                d[key] = {}
            d = d[key]
        d[path[-1]] = value

    def to_wrapper_kwargs(self) -> Dict[str, Any]:
        """
        Convert config to ContentBlockTranslationWrapper kwargs.

        Returns:
            Dictionary of parameters for wrapper initialization
        """
        kwargs = {
            'model': self.translation.model,
            'temperature': self.translation.temperature,
            'max_retries': self.retry.max_attempts,
            'quality_threshold': self.validation.quality.threshold,
            'timeout': self.translation.timeout,
        }

        # Add glossary path if enabled
        if self.glossary.enabled and self.glossary.path:
            kwargs['glossary_path'] = Path(self.glossary.path)

        return kwargs


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def load_config(
    config_path: Optional[str] = None,
    config_name: Optional[str] = None,
    work_id: Optional[str] = None,
    **overrides
) -> TranslationConfig:
    """
    Convenience function to load translation configuration.

    See TranslationConfig.load() for detailed documentation.
    """
    return TranslationConfig.load(
        config_path=config_path,
        config_name=config_name,
        work_id=work_id,
        **overrides
    )


# =============================================================================
# CLI / TESTING
# =============================================================================

def main():
    """Test config loading"""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("\n=== DEFAULT CONFIG ===")
    config = load_config()
    print(f"Quality threshold: {config.validation.quality.threshold}")
    print(f"Max retries: {config.retry.max_attempts}")
    print(f"Model: {config.translation.model}")

    print("\n=== STRICT MODE ===")
    config = load_config(config_name="strict")
    print(f"Quality threshold: {config.validation.quality.threshold}")
    print(f"Max retries: {config.retry.max_attempts}")
    print(f"Model: {config.translation.model}")

    print("\n=== FAST MODE ===")
    config = load_config(config_name="fast")
    print(f"Quality threshold: {config.validation.quality.threshold}")
    print(f"Max retries: {config.retry.max_attempts}")
    print(f"Model: {config.translation.model}")

    print("\n=== WORK OVERRIDE (D1379) ===")
    config = load_config(work_id="D1379")
    print(f"Quality threshold: {config.validation.quality.threshold}")
    print(f"Max retries: {config.retry.max_attempts}")
    print(f"Glossary enabled: {config.glossary.enabled}")

    print("\n=== DIRECT OVERRIDES (BACKWARD COMPATIBILITY) ===")
    config = load_config(max_retries=10, quality_threshold=8.0, model="gpt-4o")
    print(f"Quality threshold: {config.validation.quality.threshold}")
    print(f"Max retries: {config.retry.max_attempts}")
    print(f"Model: {config.translation.model}")

    print("\n=== COMBINATION: WORK + DIRECT OVERRIDE ===")
    config = load_config(work_id="D1379", max_retries=15)
    print(f"Quality threshold: {config.validation.quality.threshold}")
    print(f"Max retries: {config.retry.max_attempts}")
    print(f"Glossary enabled: {config.glossary.enabled}")

    print("\n=== WRAPPER KWARGS ===")
    config = load_config(config_name="strict")
    kwargs = config.to_wrapper_kwargs()
    print(f"Wrapper kwargs: {kwargs}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
