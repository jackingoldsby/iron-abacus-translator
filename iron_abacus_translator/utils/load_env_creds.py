#!/usr/bin/env python3
"""
Environment Credentials Loader

Thin wrapper around os.getenv() for retrieving API keys and credentials
from environment variables.

Migration note:
    This module previously loaded credentials from a YAML file (env_creds.yml).
    It now reads exclusively from environment variables. Set your credentials
    in your shell profile (e.g. ~/.zshrc):

        export OPENAI_API_KEY='sk-...'
        export ANTHROPIC_API_KEY='sk-ant-...'

    The public API is unchanged for backwards compatibility. The `file_path`
    and `override` parameters on load_env_credentials() are accepted but
    ignored.

Usage:
    from utils.load_env_creds import load_env_credentials

    # Load credentials from environment
    load_env_credentials()

    # Or load specific keys only
    load_env_credentials(keys=['OPENAI_API_KEY'])

    # Then access via os.getenv
    import os
    api_key = os.getenv('OPENAI_API_KEY')
"""

import os
from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)


def load_env_credentials(
    file_path=None,
    keys: Optional[List[str]] = None,
    required_keys: Optional[List[str]] = None,
    override: bool = False,
) -> Dict[str, str]:
    """
    Return a dict of currently-set environment variables for the requested keys.

    Args:
        file_path: Ignored (kept for backwards compatibility).
        keys: List of env var names to return. If None, returns all known
              credential-style vars that are currently set.
        required_keys: List of keys that must be present in the environment.
              Raises KeyError if any are missing.
        override: Ignored (kept for backwards compatibility).

    Returns:
        Dictionary of {key: value} for the requested environment variables.

    Raises:
        KeyError: If any required_keys are not set in the environment.
    """
    # Default set of well-known credential keys to look for
    default_keys = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ]

    lookup_keys = keys if keys is not None else default_keys

    # Check required keys first
    if required_keys:
        missing = [k for k in required_keys if not os.getenv(k)]
        if missing:
            raise KeyError(
                f"Required environment variables not set: {', '.join(missing)}\n"
                f"Set in ~/.zshrc:  export {missing[0]}='...'"
            )

    # Collect values
    result: Dict[str, str] = {}
    for key in lookup_keys:
        value = os.getenv(key)
        if value:
            result[key] = value

    logger.info(f"Found {len(result)} credentials in environment")
    return result


def get_openai_api_key() -> str:
    """
    Get the OpenAI API key from the environment.

    Returns:
        OpenAI API key string.

    Raises:
        RuntimeError: If OPENAI_API_KEY is not set.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set.\n"
            "Set in ~/.zshrc:  export OPENAI_API_KEY='sk-...'"
        )
    return api_key


def verify_openai_key(api_key: Optional[str] = None) -> bool:
    """
    Verify an OpenAI API key works by making a test API call.

    Args:
        api_key: API key to verify. If None, reads from environment.

    Returns:
        True if key is valid, False otherwise.
    """
    try:
        from openai import OpenAI

        if api_key is None:
            api_key = get_openai_api_key()

        client = OpenAI(api_key=api_key)

        client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )

        logger.info("OpenAI API key verified successfully")
        return True

    except Exception as e:
        logger.error(f"OpenAI API key verification failed: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("Testing environment credentials...")
    print()

    try:
        creds = load_env_credentials()
        print(f"Found {len(creds)} credentials in environment")
        if creds:
            print(f"  Keys: {', '.join(creds.keys())}")
        print()

        api_key = get_openai_api_key()
        print(f"OPENAI_API_KEY starts with: {api_key[:15]}...")
        print(f"OPENAI_API_KEY length: {len(api_key)}")
        print()

        print("Verifying key with API call...")
        if verify_openai_key(api_key):
            print("All tests passed!")
        else:
            print("API key verification failed")

    except Exception as e:
        print(f"Error: {e}")
        import sys
        sys.exit(1)
