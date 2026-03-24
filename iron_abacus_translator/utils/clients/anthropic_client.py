from __future__ import annotations
import os
from anthropic import Anthropic

from utils.clients.llm_client import llm_chat_json


def get_client() -> Anthropic:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return Anthropic(api_key=key)

def quick_chat(prompt: str) -> str:
    result = llm_chat_json(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        json_mode=False,
        component="anthropic_quick",
    )
    return result.get("text", "")
