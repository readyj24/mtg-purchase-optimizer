"""Simple disk cache for Playwright-scraped store listings.

Each entry is stored as a JSON file under .cache/{namespace}/{slug}.json.
Entries expire after TTL_SECONDS (default 24 h).  The cache is read/written
synchronously — callers hold an asyncio lock around it so writes are safe.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(".cache")
TTL_SECONDS = 24 * 60 * 60  # 24 hours


def _slug(key: str) -> str:
    """Convert a card name to a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", key.lower().strip()).strip("_") or "card"


def _path(namespace: str, key: str) -> Path:
    d = _CACHE_DIR / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_slug(key)}.json"


def load(namespace: str, key: str) -> Optional[list]:
    """Return cached list, or None if missing / expired."""
    p = _path(namespace, key)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > TTL_SECONDS:
        logger.debug("Disk cache expired (%dh old): %s/%s", int(age / 3600), namespace, key)
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        logger.info("Disk cache hit: %s/%s (%d items)", namespace, key, len(data))
        return data
    except Exception as e:
        logger.warning("Disk cache read error %s/%s: %s", namespace, key, e)
        return None


def save(namespace: str, key: str, data: list) -> None:
    """Write list to disk cache."""
    p = _path(namespace, key)
    try:
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        logger.info("Disk cache saved: %s/%s (%d items)", namespace, key, len(data))
    except Exception as e:
        logger.warning("Disk cache write error %s/%s: %s", namespace, key, e)
