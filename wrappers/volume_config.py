#!/usr/bin/env python3
"""
Volume Translation Configuration Loader

Load and validate volume translation configuration from YAML files with Pydantic.

Configuration Priority (highest to lowest):
1. Direct kwargs parameters (overrides)
2. Work-specific override file (config/volume_work_overrides/{work_id}_rules.yaml)
3. Named config (config/volume_translation_rules.{config_name}.yaml)
4. Default config (config/volume_translation_rules.yaml)
5. Hardcoded defaults (fallback if no config file)
"""

import yaml
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict

logger = logging.getLogger(__name__)


# =============================================================================
# PYDANTIC MODELS FOR CONFIG VALIDATION
# =============================================================================

class ParallelConfig(BaseModel):
    """Parallel processing configuration"""
    max_workers: int = Field(default=5, ge=1, le=50)
    timeout_per_block: int = Field(default=300, ge=1)  # 5 minutes


class ValidationConfig(BaseModel):
    """Aggregate validation configuration"""
    aggregate_quality_threshold: float = Field(default=9.5, ge=0.0, le=10.0)
    allow_footnote_mismatches: bool = False  # Zero tolerance (strict)
    block_quality_threshold: float = Field(default=9.5, ge=0.0, le=10.0)


class BlockConfigSettings(BaseModel):
    """Configuration for ContentBlockTranslationWrapper"""
    config_name: Optional[str] = None  # e.g., "strict", "fast"
    quality_threshold: Optional[float] = None
    max_retries: Optional[int] = None

    def get_overrides(self) -> Dict[str, Any]:
        """Get overrides as dictionary (exclude None values)"""
        overrides = {}
        if self.quality_threshold is not None:
            overrides['quality_threshold'] = self.quality_threshold
        if self.max_retries is not None:
            overrides['max_retries'] = self.max_retries
        return overrides


class ReportingConfig(BaseModel):
    """Reporting configuration"""
    include_per_block_stats: bool = True
    include_body_vs_nonbody_breakdown: bool = True
    save_detailed_manifest: bool = True


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = "INFO"
    log_progress: bool = True  # Show progress bar
    log_statistics: bool = True

    @field_validator('level')
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"level must be one of {allowed}, got: {v}")
        return v_upper


class VolumeConfig(BaseModel):
    """Complete volume translation configuration"""
    model_config = ConfigDict(extra='forbid')  # Reject unknown fields

    parallel: ParallelConfig = Field(default_factory=ParallelConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    block_config: BlockConfigSettings = Field(default_factory=BlockConfigSettings)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def load(
        cls,
        config_path: Optional[str] = None,
        config_name: Optional[str] = None,
        work_id: Optional[str] = None,
        **overrides
    ) -> "VolumeConfig":
        """
        Load configuration with priority system.

        Priority (highest to lowest):
        1. Direct kwargs parameters (overrides)
        2. Work-specific override file (config/volume_work_overrides/{work_id}_rules.yaml)
        3. Named config (config/volume_translation_rules.{config_name}.yaml)
        4. Default config (config/volume_translation_rules.yaml)
        5. Hardcoded defaults

        Args:
            config_path: Explicit path to config file (overrides config_name)
            config_name: Named config (e.g., "strict", "fast")
            work_id: Work ID for work-specific overrides
            **overrides: Direct parameter overrides

        Returns:
            VolumeConfig instance

        Example:
            # Use default config
            config = VolumeConfig.load()

            # Use named config
            config = VolumeConfig.load(config_name="strict")

            # Use work-specific override
            config = VolumeConfig.load(work_id="D1379")

            # Direct overrides
            config = VolumeConfig.load(max_workers=10)

            # Combination: work override + direct override
            config = VolumeConfig.load(work_id="D1379", max_workers=10)
        """
        # Start with hardcoded defaults
        config_dict = cls._get_default_dict()

        # Load base config
        base_config_path = cls._resolve_config_path(config_path, config_name)
        if base_config_path and base_config_path.exists():
            logger.info(f"Loading base volume config from: {base_config_path}")
            base_dict = cls._load_yaml(base_config_path)
            config_dict = cls._deep_merge(config_dict, base_dict)
        else:
            logger.info("Using hardcoded default volume configuration")

        # Apply work-specific overrides
        if work_id:
            work_override_path = cls._get_work_override_path(work_id)
            if work_override_path.exists():
                logger.info(f"Applying work-specific volume overrides from: {work_override_path}")
                work_dict = cls._load_yaml(work_override_path)
                config_dict = cls._deep_merge(config_dict, work_dict)
            else:
                logger.debug(f"No work-specific volume override found for work_id={work_id}")

        # Apply direct overrides
        if overrides:
            logger.info(f"Applying direct volume parameter overrides: {list(overrides.keys())}")
            override_dict = cls._convert_overrides(overrides)
            config_dict = cls._deep_merge(config_dict, override_dict)

        # Validate and create config
        try:
            config = cls(**config_dict)
            logger.info("Volume configuration loaded and validated successfully")
            return config
        except Exception as e:
            logger.error(f"Volume configuration validation failed: {e}")
            raise

    @staticmethod
    def _get_default_dict() -> Dict[str, Any]:
        """Get hardcoded default configuration"""
        return {
            "parallel": {
                "max_workers": 5,
                "timeout_per_block": 300
            },
            "validation": {
                "aggregate_quality_threshold": 9.5,
                "allow_footnote_mismatches": False,
                "block_quality_threshold": 9.5
            },
            "block_config": {
                "config_name": None,
                "quality_threshold": None,
                "max_retries": None
            },
            "reporting": {
                "include_per_block_stats": True,
                "include_body_vs_nonbody_breakdown": True,
                "save_detailed_manifest": True
            },
            "logging": {
                "level": "INFO",
                "log_progress": True,
                "log_statistics": True
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
            # Named config: config/volume_translation_rules.{name}.yaml
            return config_dir / f"volume_translation_rules.{config_name}.yaml"
        else:
            # Default config: config/volume_translation_rules.yaml
            return config_dir / "volume_translation_rules.yaml"

    @staticmethod
    def _get_work_override_path(work_id: str) -> Path:
        """Get path to work-specific override file"""
        config_dir = Path(__file__).parent.parent / "config" / "volume_work_overrides"
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
                result[key] = VolumeConfig._deep_merge(result[key], value)
            else:
                # Override value
                result[key] = value

        return result

    @staticmethod
    def _convert_overrides(overrides: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert parameter names to config structure.

        Mappings:
        - max_workers -> parallel.max_workers
        - timeout_per_block -> parallel.timeout_per_block
        - aggregate_quality_threshold -> validation.aggregate_quality_threshold
        - allow_footnote_mismatches -> validation.allow_footnote_mismatches
        - block_quality_threshold -> validation.block_quality_threshold
        """
        config_dict: Dict[str, Any] = {
            "parallel": {},
            "validation": {},
            "block_config": {},
            "logging": {}
        }

        # Map parameter names
        mappings = {
            'max_workers': ('parallel', 'max_workers'),
            'timeout_per_block': ('parallel', 'timeout_per_block'),
            'aggregate_quality_threshold': ('validation', 'aggregate_quality_threshold'),
            'allow_footnote_mismatches': ('validation', 'allow_footnote_mismatches'),
            'block_quality_threshold': ('validation', 'block_quality_threshold'),
            'block_config_name': ('block_config', 'config_name'),
            'block_quality_threshold_override': ('block_config', 'quality_threshold'),
            'block_max_retries': ('block_config', 'max_retries'),
        }

        for key, value in overrides.items():
            if key in mappings:
                path = mappings[key]
                VolumeConfig._set_nested(config_dict, path, value)
            else:
                # Unknown parameter - let Pydantic validation handle it
                logger.warning(f"Unknown volume parameter: {key}")

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


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def load_volume_config(
    config_path: Optional[str] = None,
    config_name: Optional[str] = None,
    work_id: Optional[str] = None,
    **overrides
) -> VolumeConfig:
    """
    Convenience function to load volume translation configuration.

    See VolumeConfig.load() for detailed documentation.
    """
    return VolumeConfig.load(
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
    config = load_volume_config()
    print(f"Max workers: {config.parallel.max_workers}")
    print(f"Aggregate quality threshold: {config.validation.aggregate_quality_threshold}")
    print(f"Allow footnote mismatches: {config.validation.allow_footnote_mismatches}")

    print("\n=== STRICT MODE ===")
    config = load_volume_config(config_name="strict")
    print(f"Max workers: {config.parallel.max_workers}")
    print(f"Aggregate quality threshold: {config.validation.aggregate_quality_threshold}")
    print(f"Block config name: {config.block_config.config_name}")

    print("\n=== FAST MODE ===")
    config = load_volume_config(config_name="fast")
    print(f"Max workers: {config.parallel.max_workers}")
    print(f"Aggregate quality threshold: {config.validation.aggregate_quality_threshold}")
    print(f"Block config name: {config.block_config.config_name}")

    print("\n=== DIRECT OVERRIDES ===")
    config = load_volume_config(max_workers=10, aggregate_quality_threshold=8.0)
    print(f"Max workers: {config.parallel.max_workers}")
    print(f"Aggregate quality threshold: {config.validation.aggregate_quality_threshold}")

    print("\n=== WORK OVERRIDE (D1379) ===")
    config = load_volume_config(work_id="D1379")
    print(f"Max workers: {config.parallel.max_workers}")
    print(f"Aggregate quality threshold: {config.validation.aggregate_quality_threshold}")

    print("\n=== COMBINATION: WORK + DIRECT OVERRIDE ===")
    config = load_volume_config(work_id="D1379", max_workers=15)
    print(f"Max workers: {config.parallel.max_workers}")
    print(f"Aggregate quality threshold: {config.validation.aggregate_quality_threshold}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
