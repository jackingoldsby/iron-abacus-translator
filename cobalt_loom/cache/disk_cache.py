"""File-based HTML cache for scraped pages."""

import hashlib
import json
import logging
import time
from pathlib import Path

from config.defaults import DEFAULT_CACHE_DIR

logger = logging.getLogger(__name__)


class DiskCache:
    """Simple file-based cache keyed by URL, with optional TTL."""

    def __init__(self, cache_dir: str = DEFAULT_CACHE_DIR, ttl_days: int = 30):
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_days * 86400

    def _key_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()[:16]
        return self.cache_dir / f"{h}.json"

    def get(self, url: str) -> str | None:
        path = self._key_path(url)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - data.get("ts", 0) > self.ttl_seconds:
            path.unlink(missing_ok=True)
            return None
        return data.get("content")

    def put(self, url: str, content: str):
        path = self._key_path(url)
        data = {"url": url, "ts": time.time(), "content": content}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def clear(self):
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
        logger.info(f"Cache cleared: {self.cache_dir}")
