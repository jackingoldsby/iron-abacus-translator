#!/usr/bin/env python3
"""
Lightweight DeepSeek client for Crimson Folio.

Used only for cover image research (analyzing book metadata to suggest
art search terms). Much simpler than iron_abacus's multi-provider factory.
"""

import os
from pathlib import Path

from openai import OpenAI


def get_deepseek_client() -> OpenAI:
    """Get a DeepSeek client with API key loaded from .env."""
    from dotenv import load_dotenv

    # Try crimson_folio .env first, then workspace root, then iron_abacus
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
