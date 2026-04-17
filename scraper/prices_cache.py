"""Daily price cache from MTGJSON AllPricesToday.json.

Downloads the file once per day and caches it to disk.  Provides a fast
UUID -> store prices lookup used by the card-kingdom scraper.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PRICES_URL = "https://mtgjson.com/api/v5/AllPricesToday.json"
CACHE_FILE = Path(__file__).parent.parent / ".cache" / "prices_today.json"
CACHE_TTL  = 60 * 60 * 24  # 24 hours

# In-memory copy once loaded
_prices_data: Optional[dict] = None
_load_lock = asyncio.Lock()
_loading = False


async def get_prices_for_uuid(uuid: str) -> dict:
    """Return {provider: {normal_price, foil_price}} for a MTGJSON UUID."""
    data = await _ensure_loaded()
    entry = data.get(uuid, {})
    paper = entry.get("paper", {})
    result = {}
    for provider, pdata in paper.items():
        retail = pdata.get("retail", {})
        normal = _latest(retail.get("normal", {}))
        foil   = _latest(retail.get("foil", {}))
        if normal is not None or foil is not None:
            result[provider] = {"normal": normal, "foil": foil}
    return result


def _latest(history: dict) -> Optional[float]:
    if not history:
        return None
    val = history[max(history.keys())]
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


async def _ensure_loaded() -> dict:
    global _prices_data
    if _prices_data is not None:
        return _prices_data

    async with _load_lock:
        if _prices_data is not None:
            return _prices_data
        _prices_data = await _load()
        return _prices_data


async def _load() -> dict:
    """Load prices from disk cache or download fresh."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _cache_is_fresh():
        logger.info("Loading prices from disk cache %s", CACHE_FILE)
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            return payload.get("data", {})
        except Exception as e:
            logger.warning("Cache read failed (%s), re-downloading", e)

    return await _download_and_cache()


def _cache_is_fresh() -> bool:
    if not CACHE_FILE.exists():
        return False
    age = time.time() - CACHE_FILE.stat().st_mtime
    return age < CACHE_TTL


async def _download_and_cache() -> dict:
    logger.info("Downloading AllPricesToday.json from MTGJSON (~50 MB, once per day)…")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(PRICES_URL)
            resp.raise_for_status()
            payload = resp.json()

        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        logger.info("Price cache written to %s", CACHE_FILE)
        return payload.get("data", {})
    except Exception as e:
        logger.error("Failed to download price data: %s", e)
        return {}
