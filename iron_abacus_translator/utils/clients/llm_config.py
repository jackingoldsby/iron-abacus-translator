"""
LLM Client Factory

Resolves provider and model from environment variables with per-component overrides.

Env var hierarchy (first match wins):
    Provider: explicit arg > {COMPONENT}_LLM_PROVIDER > LLM_PROVIDER > "openai"
    Model:    explicit arg > {COMPONENT}_LLM_MODEL > provider default

Examples:
    LLM_PROVIDER=anthropic                        # Global switch
    TRANSLATOR_LLM_PROVIDER=anthropic              # Just translation uses Claude
    TRANSLATOR_LLM_MODEL=claude-sonnet-4-20250514  # Specific model
    CLEANUP_LLM_PROVIDER=openai                    # Cleanup stays on GPT
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from utils.clients.llm_client import LLMClient, OpenAILLMClient, AnthropicLLMClient

logger = logging.getLogger(__name__)

_PROVIDER_DEFAULTS = {
    "openai": "gpt-4.1-nano",
    "anthropic": "claude-sonnet-4-20250514",
}

# Component-specific model defaults (overrides provider default)
# Translation needs higher quality; cleanup/validation can use cheaper models
_COMPONENT_MODEL_DEFAULTS = {
    "openai": {
        "translator": "gpt-4.1-mini",
    },
    "anthropic": {
        "translator": "claude-sonnet-4-20250514",
    },
}


def get_llm_client(
    component: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> LLMClient:
    """
    Create an LLM client based on environment config.

    Args:
        component: Component name (e.g., "translator", "validator", "cleanup").
                   Used to look up {COMPONENT}_LLM_PROVIDER and {COMPONENT}_LLM_MODEL.
        provider: Explicit provider override ("openai" or "anthropic").
        model: Explicit model override.
        api_key: Explicit API key override.

    Returns:
        Configured LLMClient instance.

    Model resolution order:
        1. Explicit ``model`` arg
        2. {COMPONENT}_LLM_MODEL env var
        3. Component default (_COMPONENT_MODEL_DEFAULTS)
        4. Provider default (_PROVIDER_DEFAULTS)
    """
    # Resolve provider
    resolved_provider = provider
    if resolved_provider is None and component:
        env_key = f"{component.upper()}_LLM_PROVIDER"
        resolved_provider = os.getenv(env_key)
    if resolved_provider is None:
        resolved_provider = os.getenv("LLM_PROVIDER", "openai")

    resolved_provider = resolved_provider.lower()

    # Resolve model
    resolved_model = model
    if resolved_model is None and component:
        env_key = f"{component.upper()}_LLM_MODEL"
        resolved_model = os.getenv(env_key)
    if resolved_model is None and component:
        resolved_model = _COMPONENT_MODEL_DEFAULTS.get(
            resolved_provider, {}
        ).get(component)
    if resolved_model is None:
        resolved_model = _PROVIDER_DEFAULTS.get(resolved_provider, "gpt-4.1-nano")

    logger.debug(
        f"LLM config: component={component}, provider={resolved_provider}, model={resolved_model}"
    )

    if resolved_provider == "anthropic":
        return AnthropicLLMClient(model=resolved_model, api_key=api_key)
    elif resolved_provider == "openai":
        return OpenAILLMClient(model=resolved_model, api_key=api_key)
    else:
        raise ValueError(
            f"Unknown LLM provider: {resolved_provider!r}. "
            f"Supported: openai, anthropic"
        )
