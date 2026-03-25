"""
LLM Client Abstraction Layer

Unified interface for OpenAI and Anthropic LLM providers.
Supports provider switching via environment variables and per-component overrides.

Usage:
    from utils.clients import llm_chat_json, get_llm_client, LLMRequest

    # Simple: send messages, get parsed dict
    result = llm_chat_json(messages, model="gpt-4.1-nano", json_mode=True)

    # Full control:
    client = get_llm_client(component="translator")
    response = client.chat(LLMRequest(messages=messages, json_mode=True))
    print(response.text, response.parsed)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Models that don't support custom temperature
_NO_CUSTOM_TEMPERATURE_MODELS = {"gpt-4.1-nano"}


@dataclass
class LLMRequest:
    """Request payload for an LLM chat call."""
    messages: List[Dict[str, str]]
    model: Optional[str] = None  # None = use client default
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    json_mode: bool = False
    timeout: Optional[int] = None


@dataclass
class LLMResponse:
    """Response from an LLM chat call."""
    text: str
    parsed: Optional[Dict[str, Any]] = None  # JSON-parsed text (if json_mode)
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM clients. Implement chat() to add a new provider."""

    def chat(self, request: LLMRequest) -> LLMResponse: ...


# ---------------------------------------------------------------------------
# OpenAI implementation
# ---------------------------------------------------------------------------

class OpenAILLMClient:
    """LLM client wrapping OpenAI's chat completions API."""

    def __init__(self, model: str = "gpt-4.1-nano", api_key: Optional[str] = None, base_url: Optional[str] = None, provider: str = "openai"):
        from openai import OpenAI
        self.model = model
        self.default_model = model
        self.provider = provider
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("No API key provided and OPENAI_API_KEY not set")
        kwargs = {"api_key": key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    def chat(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model

        params: Dict[str, Any] = {
            "model": model,
            "messages": request.messages,
        }

        # gpt-4.1-nano doesn't support custom temperature
        if request.temperature is not None and model not in _NO_CUSTOM_TEMPERATURE_MODELS:
            params["temperature"] = request.temperature

        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens

        if request.json_mode:
            params["response_format"] = {"type": "json_object"}

        if request.timeout is not None:
            params["timeout"] = request.timeout

        resp = self._client.chat.completions.create(**params)
        text = resp.choices[0].message.content or ""

        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }

        parsed = None
        if request.json_mode:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("JSON mode requested but response is not valid JSON")

        return LLMResponse(text=text, parsed=parsed, model=model, usage=usage)


# ---------------------------------------------------------------------------
# Anthropic implementation
# ---------------------------------------------------------------------------

class AnthropicLLMClient:
    """LLM client wrapping Anthropic's messages API."""

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: Optional[str] = None, provider: str = "anthropic"):
        from anthropic import Anthropic
        self.model = model
        self.default_model = model
        self.provider = provider
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = Anthropic(api_key=key)

    def chat(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model

        # Anthropic requires system message to be separate
        system_text = ""
        messages = []
        for msg in request.messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                messages.append(msg)

        # For JSON mode, use prefill technique
        if request.json_mode and (not messages or messages[-1]["role"] != "assistant"):
            messages.append({"role": "assistant", "content": "{"})

        params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
        }

        if system_text:
            params["system"] = system_text

        if request.temperature is not None:
            params["temperature"] = request.temperature

        resp = self._client.messages.create(**params)
        text = resp.content[0].text

        # If we used prefill, prepend the opening brace
        if request.json_mode and messages and messages[-1]["role"] == "assistant":
            text = "{" + text

        usage = {}
        if resp.usage:
            usage = {
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            }

        parsed = None
        if request.json_mode:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("JSON mode requested but response is not valid JSON")

        return LLMResponse(text=text, parsed=parsed, model=model, usage=usage)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def llm_chat_json(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[int] = None,
    json_mode: bool = True,
    client: Optional[LLMClient] = None,
    component: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send messages to an LLM and get back a parsed JSON dict.

    This is the simplest way to call an LLM. Covers ~80% of use cases.

    Args:
        messages: Chat messages (system + user)
        model: Override model name
        temperature: Override temperature
        max_tokens: Override max tokens
        timeout: Request timeout in seconds
        json_mode: Request JSON output (default True)
        client: Pre-configured LLMClient (skips factory lookup)
        component: Component name for provider/model resolution

    Returns:
        Parsed JSON dict from the LLM response

    Raises:
        RuntimeError: If response cannot be parsed as JSON
    """
    if client is None:
        from utils.clients.llm_config import get_llm_client
        client = get_llm_client(component=component, model=model)

    request = LLMRequest(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
        timeout=timeout,
    )

    response = client.chat(request)

    if json_mode and response.parsed is None:
        raise RuntimeError(
            f"LLM response is not valid JSON: {response.text[:500]}"
        )

    return response.parsed if json_mode else {"text": response.text}
