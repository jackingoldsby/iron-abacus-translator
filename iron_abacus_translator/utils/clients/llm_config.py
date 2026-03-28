"""
LLM Client Factory

Resolves provider and model from environment variables with per-component overrides.

Env var hierarchy (first match wins):
    Provider: explicit arg > {COMPONENT}_LLM_PROVIDER > LLM_PROVIDER > "openai"
    Model:    explicit arg > {COMPONENT}_LLM_MODEL > provider default

Supported providers: openai, anthropic, deepseek (+ any OpenAI-compatible with {PROVIDER}_BASE_URL)

Examples:
    LLM_PROVIDER=anthropic                        # Global switch
    LLM_PROVIDER=deepseek                         # Use DeepSeek
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
    "deepseek": "deepseek-chat",
}

_PROVIDER_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
}

_PROVIDER_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# Component-specific model defaults (overrides provider default)
# Translation needs higher quality; cleanup/validation can use cheaper models
_COMPONENT_MODEL_DEFAULTS = {
    "openai": {
        "translator": "gpt-4.1-mini",
        "validator": "gpt-4.1-nano",
    },
    "anthropic": {
        "translator": "claude-sonnet-4-20250514",
        "validator": "claude-sonnet-4-20250514",
    },
    "deepseek": {
        "translator": "deepseek-chat",
        "validator": "deepseek-chat",
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
        return AnthropicLLMClient(model=resolved_model, api_key=api_key, provider=resolved_provider)
    elif resolved_provider == "openai":
        return OpenAILLMClient(model=resolved_model, api_key=api_key, provider=resolved_provider)
    else:
        # OpenAI-compatible providers (deepseek, local endpoints, etc.)
        base_url = _PROVIDER_BASE_URLS.get(resolved_provider)
        if base_url is None:
            # Check for custom base URL via env var
            base_url = os.getenv(f"{resolved_provider.upper()}_BASE_URL")
        if base_url is None:
            raise ValueError(
                f"Unknown LLM provider: {resolved_provider!r}. "
                f"Supported: openai, anthropic, deepseek (or set {resolved_provider.upper()}_BASE_URL)"
            )
        # Resolve API key from provider-specific env var
        if api_key is None:
            env_key = _PROVIDER_API_KEY_ENV.get(
                resolved_provider, f"{resolved_provider.upper()}_API_KEY"
            )
            api_key = os.getenv(env_key)
        return OpenAILLMClient(model=resolved_model, api_key=api_key, base_url=base_url, provider=resolved_provider)
