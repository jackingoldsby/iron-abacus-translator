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

    # Default timeouts by usage pattern (seconds)
    DEFAULT_TIMEOUT = 120
    CLEANUP_TIMEOUT = 60
    MAX_RETRIES = 3

    def __init__(self, model: str = "gpt-4.1-nano", api_key: Optional[str] = None, base_url: Optional[str] = None, provider: str = "openai"):
        from openai import OpenAI
        self.model = model
        self.default_model = model
        self.provider = provider
        self.base_url = base_url
        if api_key:
            key = api_key
        elif provider == "openai":
            key = os.getenv("OPENAI_API_KEY")
        else:
            # For non-OpenAI providers (deepseek, etc.), try provider-specific key first
            key = os.getenv(f"{provider.upper()}_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(f"No API key provided and {provider.upper()}_API_KEY not set")
        self._api_key_suffix = key[-4:] if len(key) >= 4 else "????"
        kwargs = {"api_key": key, "timeout": self.DEFAULT_TIMEOUT}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    @property
    def key_suffix(self) -> str:
        """Last 4 chars of the API key (for diagnostics)."""
        return self._api_key_suffix

    def verify(self) -> bool:
        """Test API connectivity with a minimal call. Returns True on success, raises on failure."""
        import time as _time
        target = self.base_url or "api.openai.com"
        logger.info(f"  Verifying {self.provider} API (key=...{self._api_key_suffix}, endpoint={target})")
        t0 = _time.monotonic()
        try:
            self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                timeout=15,
            )
            elapsed = _time.monotonic() - t0
            logger.info(f"  {self.provider} OK ({elapsed:.1f}s)")
            return True
        except Exception as e:
            elapsed = _time.monotonic() - t0
            err_type = type(e).__name__
            raise RuntimeError(
                f"Authentication failed for {self.provider} "
                f"(key=...{self._api_key_suffix}, endpoint={target}): "
                f"{err_type}: {e}"
            ) from e

    def chat(self, request: LLMRequest) -> LLMResponse:
        import time as _time

        model = request.model or self.default_model
        timeout = request.timeout or self.DEFAULT_TIMEOUT

        params: Dict[str, Any] = {
            "model": model,
            "messages": request.messages,
            "timeout": timeout,
        }

        # gpt-4.1-nano doesn't support custom temperature
        if request.temperature is not None and model not in _NO_CUSTOM_TEMPERATURE_MODELS:
            params["temperature"] = request.temperature

        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens

        if request.json_mode:
            params["response_format"] = {"type": "json_object"}

        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            t0 = _time.monotonic()
            try:
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

            except Exception as e:
                elapsed = _time.monotonic() - t0
                err_type = type(e).__name__
                is_timeout = "timeout" in err_type.lower() or "timed out" in str(e).lower()

                if is_timeout:
                    logger.warning(
                        f"[{self.provider}] Timeout on attempt {attempt}/{self.MAX_RETRIES} "
                        f"({elapsed:.1f}s, model={model})"
                    )
                else:
                    logger.warning(
                        f"[{self.provider}] Error on attempt {attempt}/{self.MAX_RETRIES}: "
                        f"{err_type}: {e} ({elapsed:.1f}s)"
                    )

                last_error = e
                if attempt < self.MAX_RETRIES:
                    _time.sleep(min(2 ** attempt, 8))

        raise last_error


# ---------------------------------------------------------------------------
# Anthropic implementation
# ---------------------------------------------------------------------------

class AnthropicLLMClient:
    """LLM client wrapping Anthropic's messages API."""

    DEFAULT_TIMEOUT = 120
    MAX_RETRIES = 3

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: Optional[str] = None, provider: str = "anthropic"):
        from anthropic import Anthropic
        self.model = model
        self.default_model = model
        self.provider = provider
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._api_key_suffix = key[-4:] if len(key) >= 4 else "????"
        self._client = Anthropic(api_key=key, timeout=self.DEFAULT_TIMEOUT)

    @property
    def key_suffix(self) -> str:
        """Last 4 chars of the API key (for diagnostics)."""
        return self._api_key_suffix

    def verify(self) -> bool:
        """Test API connectivity with a minimal call. Returns True on success, raises on failure."""
        import time as _time
        logger.info(f"  Verifying {self.provider} API (key=...{self._api_key_suffix})")
        t0 = _time.monotonic()
        try:
            self._client.messages.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                timeout=15,
            )
            elapsed = _time.monotonic() - t0
            logger.info(f"  {self.provider} OK ({elapsed:.1f}s)")
            return True
        except Exception as e:
            elapsed = _time.monotonic() - t0
            err_type = type(e).__name__
            raise RuntimeError(
                f"Authentication failed for {self.provider} "
                f"(key=...{self._api_key_suffix}): "
                f"{err_type}: {e}"
            ) from e

    def chat(self, request: LLMRequest) -> LLMResponse:
        import time as _time

        model = request.model or self.default_model
        timeout = request.timeout or self.DEFAULT_TIMEOUT

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
            "timeout": timeout,
        }

        if system_text:
            params["system"] = system_text

        if request.temperature is not None:
            params["temperature"] = request.temperature

        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            t0 = _time.monotonic()
            try:
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

            except Exception as e:
                elapsed = _time.monotonic() - t0
                err_type = type(e).__name__
                is_timeout = "timeout" in err_type.lower() or "timed out" in str(e).lower()

                if is_timeout:
                    logger.warning(
                        f"[{self.provider}] Timeout on attempt {attempt}/{self.MAX_RETRIES} "
                        f"({elapsed:.1f}s, model={model})"
                    )
                else:
                    logger.warning(
                        f"[{self.provider}] Error on attempt {attempt}/{self.MAX_RETRIES}: "
                        f"{err_type}: {e} ({elapsed:.1f}s)"
                    )

                last_error = e
                if attempt < self.MAX_RETRIES:
                    _time.sleep(min(2 ** attempt, 8))

        raise last_error


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
