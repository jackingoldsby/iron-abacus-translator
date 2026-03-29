#!/usr/bin/env python3
"""
Lightweight DeepSeek client for Azure Register.

Used for catalog enrichment prompts. OpenAI-compatible API.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


@dataclass
class LLMRequest:
    """Request payload for an LLM chat call."""
    messages: List[Dict[str, str]]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@dataclass
class LLMResponse:
    """Response from an LLM chat call."""
    text: str
    parsed: Optional[Dict[str, Any]] = None
    usage: Dict[str, int] = field(default_factory=dict)


class DeepSeekClient:
    """Thin DeepSeek client via OpenAI-compatible API."""

    def __init__(self, model: str = "deepseek-chat", api_key: Optional[str] = None):
        self.model = model
        key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY not found. Set it in .env or as environment variable."
            )
        self._client = OpenAI(api_key=key, base_url="https://api.deepseek.com")

    def chat(self, request: LLMRequest) -> LLMResponse:
        """Send a chat request and return the response."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": request.messages,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens

        resp = self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }

        # Try to parse JSON from response
        parsed = None
        clean = text
        if "```json" in clean:
            clean = clean.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in clean:
            clean = clean.split("```", 1)[1].rsplit("```", 1)[0]
        try:
            parsed = json.loads(clean.strip())
        except json.JSONDecodeError:
            pass

        return LLMResponse(text=text, parsed=parsed, usage=usage)


def get_deepseek_client(model: str = "deepseek-chat") -> DeepSeekClient:
    """Get a DeepSeek client with API key loaded from .env."""
    from dotenv import load_dotenv

    for env_path in [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator" / ".env",
    ]:
        if env_path.exists():
            load_dotenv(env_path)
            break
    else:
        load_dotenv()

    return DeepSeekClient(model=model)
