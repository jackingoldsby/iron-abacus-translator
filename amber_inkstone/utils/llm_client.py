#!/usr/bin/env python3
"""
Lightweight DeepSeek client for Amber Inkstone.

Used only for period art research — analyzing dynasty context to generate
search queries. Same pattern as crimson_folio/utils/llm_client.py.
"""

import os
from pathlib import Path

from openai import OpenAI


def get_deepseek_client() -> OpenAI:
    """Get a DeepSeek client with API key loaded from .env."""
    from dotenv import load_dotenv

    # Try amber_inkstone .env first, then workspace root, then iron_abacus
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

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY not found. Set it in .env or as environment variable."
        )

    return OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )
