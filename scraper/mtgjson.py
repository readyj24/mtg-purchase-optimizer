"""MTGJSON helpers: map (set_code, collector_number) -> MTGJSON UUID.

UUID lookup is needed to query AllPricesToday.json.
We fetch per-set JSON files (cards only, no prices) and cache them.
"""

import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MTGJSON_BASE = "https://mtgjson.com/api/v5"

# set_code -> {collector_number -> uuid}
_uuid_cache: dict[str, dict[str, str]] = {}
_uuid_lock: dict[str, asyncio.Lock] = {}


async def get_uuid(set_code: str, collector_number: str) -> Optional[str]:
    """Return the MTGJSON UUID for a (set_code, collector_number) pair."""
    key = set_code.upper()
    mapping = await _ensure_uuid_map(key)
    # Try exact, then stripped leading zeros
    cn = collector_number
    return (
        mapping.get(cn)
        or mapping.get(cn.lstrip("0") or "0")
        or mapping.get(cn.zfill(3))
    )


async def _ensure_uuid_map(set_code: str) -> dict[str, str]:
    if set_code in _uuid_cache:
        return _uuid_cache[set_code]

    if set_code not in _uuid_lock:
        _uuid_lock[set_code] = asyncio.Lock()

    async with _uuid_lock[set_code]:
        if set_code in _uuid_cache:
            return _uuid_cache[set_code]

        mapping = await _fetch_uuid_map(set_code)
        _uuid_cache[set_code] = mapping
        return mapping


async def _fetch_uuid_map(set_code: str) -> dict[str, str]:
    url = f"{MTGJSON_BASE}/{set_code}.json"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("MTGJSON set fetch failed for %s: %s", set_code, e)
        return {}

    mapping: dict[str, str] = {}
    for card in data.get("data", {}).get("cards", []):
        cn = str(card.get("number", "")).strip()
        uuid = card.get("uuid")
        if cn and uuid:
            mapping[cn] = uuid
    return mapping
