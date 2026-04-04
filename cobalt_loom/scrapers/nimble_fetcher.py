"""Nimble SDK-based HTML fetcher — alternative to direct httpx requests.

Uses Nimble's Extract API (nimble-python SDK) for anti-bot bypass and
reliable extraction. Falls back gracefully to direct requests if Nimble
is unavailable or unconfigured.

Requires: pip install nimble-python
API key: set NIMBLE_API_TOKEN in environment or .env file.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_nimble_client = None


def get_nimble_token() -> str | None:
    """Get Nimble API token from environment or .env file."""
    # Check both NIMBLE_API_TOKEN and NIMBLE_API_KEY in environment
    for env_var in ["NIMBLE_API_TOKEN", "NIMBLE_API_KEY"]:
        token = os.environ.get(env_var)
        if token:
            return token

    for env_path in [
        Path.home() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
        Path(__file__).resolve().parents[2] / "iron_abacus_translator" / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                for prefix in ["NIMBLE_API_TOKEN=", "NIMBLE_API_KEY="]:
                    if line.startswith(prefix):
                        return line.split("=", 1)[1].strip().strip("'\"")

    return None


def _get_client():
    """Lazy-initialize the Nimble SDK client."""
    global _nimble_client
    if _nimble_client is not None:
        return _nimble_client

    token = get_nimble_token()
    if not token:
        return None

    try:
        from nimble_python import Nimble
        _nimble_client = Nimble(api_key=token)
        return _nimble_client
    except ImportError:
        logger.warning("nimble-python not installed — pip install nimble-python")
        return None


def nimble_extract(url: str, render: bool = True, stealth: bool = False) -> str | None:
    """Fetch a URL using the Nimble SDK.

    Args:
        url: The URL to extract content from.
        render: Enable JavaScript rendering (needed for dynamic pages).
        stealth: Use vx10 stealth driver for anti-bot bypass.

    Returns:
        Extracted HTML string, or None if Nimble is unavailable.
    """
    client = _get_client()
    if not client:
        logger.debug("No Nimble client available — falling back to direct requests")
        return None

    kwargs = {
        "url": url,
        "render": render,
        "country": "TW",
        "locale": "zh-TW",
    }
    if stealth:
        kwargs["driver"] = "vx10"

    try:
        result = client.extract(**kwargs)
        html = result.data.html
        if html:
            logger.debug(f"Nimble extracted {len(html)} chars from {url}")
            return html

        logger.warning(f"Nimble returned empty content for {url}")
        return None

    except Exception as e:
        logger.warning(f"Nimble extraction failed for {url}: {e}")
        return None


def nimble_fetch_raw(url: str) -> str | None:
    """Fetch raw content from a URL via Nimble (no rendering).

    Uses vx6 fast HTTP driver — suitable for API endpoints that return JSON.
    """
    client = _get_client()
    if not client:
        return None

    try:
        result = client.extract(url=url, render=False)
        html = result.data.html
        if html:
            logger.debug(f"Nimble fetched {len(html)} chars from {url}")
            return html
        return None
    except Exception as e:
        logger.warning(f"Nimble fetch failed for {url}: {e}")
        return None


def is_nimble_available() -> bool:
    """Check if Nimble SDK is configured and available."""
    return _get_client() is not None
