from __future__ import annotations
import os
from openai import OpenAI

from utils.clients.llm_client import llm_chat_json


def get_client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    return OpenAI(api_key=key)

def quick_chat(prompt: str) -> str:
    result = llm_chat_json(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4.1-nano",
        max_tokens=200,
        json_mode=False,
        component="openai_quick",
    )
    return result.get("text", "")
