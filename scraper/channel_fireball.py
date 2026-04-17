"""TCGPlayer price scraper (used for Channel Fireball, which is TCGPlayer-powered).

Strategy
--------
CFB's website redirects all product pages to tcgplayer.com.  We scrape
TCGPlayer directly.

One Playwright navigation per card name fetches all TCGPlayer listings via
the internal search API.  Results are cached in memory for the session.
Per-printing price lookups then hit the cache instantly.

Matching Scryfall printings to TCGPlayer results
-------------------------------------------------
TCGPlayer results include:
  - customAttributes["number"]  → collector number (may have leading zeros)
  - foilOnly                    → True for foil-only products
  - setName                     → set display name (not always identical to Scryfall)
  - productUrlName / setUrlName → for building the canonical product URL

We match by collector number and foil flag; set name is used as a secondary
tie-breaker when collector numbers collide across sets (rare, but possible).
"""

import asyncio
import json
import logging
import re
from typing import Optional
from urllib.parse import quote, quote_plus

from scraper.browser import get_browser, new_page
from scraper.disk_cache import load as disk_load, save as disk_save

logger = logging.getLogger(__name__)

BASE_TCG = "https://www.tcgplayer.com"
_NAMESPACE = "tcg"

# Per-card results cache: card_name_lower -> list of parsed TCG items
_cache: dict[str, list[dict]] = {}
_locks: dict[str, asyncio.Lock] = {}


def search_url(card_name: str) -> str:
    return f"{BASE_TCG}/search/magic/product?q={quote_plus(card_name)}&view=grid"


async def get_prices(
    card_name: str,
    set_code: str,
    set_name: str,
    foil: bool,
    collector_number: str = "",
) -> dict:
    """Return TCGPlayer price/qty for one specific printing."""
    all_listings = await _get_all_for_card(card_name)
    match = _find_match(all_listings, set_name, collector_number, foil)

    if match:
        return {
            "price":     match["price"],
            "quantity":  match["quantity"],
            "url":       match["url"],
            "condition": "NM",
            "error":     None if match["price"] is not None else "Out of stock",
        }

    return {
        "price":    None,
        "quantity": None,
        "url":      search_url(card_name),
        "condition": None,
        "error":    "Not listed on TCGPlayer",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_all_for_card(card_name: str) -> list[dict]:
    key = card_name.lower().strip()
    if key in _cache:
        return _cache[key]

    # Check disk cache before launching Playwright
    cached = disk_load(_NAMESPACE, key)
    if cached is not None:
        _cache[key] = cached
        return cached

    if key not in _locks:
        _locks[key] = asyncio.Lock()
    async with _locks[key]:
        if key in _cache:
            return _cache[key]
        # Re-check disk inside lock (another coroutine may have written it)
        cached = disk_load(_NAMESPACE, key)
        if cached is not None:
            _cache[key] = cached
            return cached
        listings = await _fetch(card_name)
        _cache[key] = listings
        disk_save(_NAMESPACE, key, listings)
        return listings


async def _fetch(card_name: str) -> list[dict]:
    url = search_url(card_name)
    try:
        browser = await get_browser()
        page, ctx = await new_page(browser)
        try:
            # Use expect_response context manager — Playwright buffers the response
            # body for us before we close the context, avoiding race conditions.
            async with page.expect_response(
                lambda r: "mp-search-api.tcgplayer.com/v1/search/request" in r.url,
                timeout=25000,
            ) as resp_info:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            response = await resp_info.value
            data = await response.json()
            return _parse(data, card_name)
        except Exception as inner_e:
            logger.warning("TCGPlayer inner error for '%s': %s", card_name, inner_e)
            return []
        finally:
            await ctx.close()
    except Exception as e:
        logger.warning("TCGPlayer fetch error for '%s': %s", card_name, e)
        return []


def _parse(data: dict, card_name: str) -> list[dict]:
    try:
        results = data["results"][0]["results"]
    except (KeyError, IndexError, TypeError):
        logger.warning("TCGPlayer: unexpected response shape for '%s'", card_name)
        return []

    items = []
    card_name_lower = card_name.lower()

    for product in results:
        # Filter to Magic singles only
        product_name: str = product.get("productName", "")
        if card_name_lower not in product_name.lower():
            continue

        attrs = product.get("customAttributes") or {}
        cn_raw: str = attrs.get("number") or ""
        cn = cn_raw.lstrip("0") or "0"

        foil_only: bool = bool(product.get("foilOnly") or False)
        set_name_tcg: str = product.get("setName") or ""

        # Price: prefer lowestPrice NM, fall back to marketPrice
        price_val: Optional[float] = None
        lowest = product.get("lowestPrice")
        market = product.get("marketPrice")
        if lowest is not None:
            try:
                price_val = float(lowest) or None
            except (TypeError, ValueError):
                pass
        if price_val is None and market is not None:
            try:
                price_val = float(market) or None
            except (TypeError, ValueError):
                pass

        # Stock: TCGPlayer doesn't expose exact stock in search results
        stock: Optional[int] = None
        total_listings = product.get("totalListings")
        if total_listings:
            try:
                stock = int(total_listings)
            except (TypeError, ValueError):
                pass

        # Build canonical product URL
        set_url = product.get("setUrlName") or ""
        product_url = product.get("productUrlName") or ""
        if set_url and product_url:
            full_url = f"{BASE_TCG}/magic/{quote(set_url, safe='')}/{quote(product_url, safe='')}"
        else:
            product_id = product.get("productId")
            full_url = f"{BASE_TCG}/product/{product_id}" if product_id else search_url(card_name)

        items.append({
            "collector_number": cn,
            "set_name":         set_name_tcg,
            "foil":             foil_only,
            "price":            price_val,
            "quantity":         stock,
            "url":              full_url,
        })

    return items


def _find_match(
    listings: list[dict],
    set_name: str,
    collector_number: str,
    foil: bool,
) -> Optional[dict]:
    cn = (collector_number or "").lstrip("0") or "0"
    set_name_lower = set_name.lower()

    # Exact match: collector number + foil + set name (substring)
    for item in listings:
        if item["foil"] != foil:
            continue
        if item["collector_number"] != cn:
            continue
        if set_name_lower in item["set_name"].lower() or item["set_name"].lower() in set_name_lower:
            return item

    # Relax set name: match by collector number + foil only
    for item in listings:
        if item["foil"] != foil:
            continue
        if item["collector_number"] != cn:
            continue
        return item

    # Final fallback: foil flag + set name (no collector number)
    for item in listings:
        if item["foil"] != foil:
            continue
        if set_name_lower in item["set_name"].lower() or item["set_name"].lower() in set_name_lower:
            return item

    return None
