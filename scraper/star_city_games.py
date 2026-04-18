"""Star City Games price scraper (Playwright + BeautifulSoup).

Strategy
--------
One Playwright search per card name fetches all SCG listings for that
card.  Results are cached in memory for the session.  Per-printing
price lookups then hit the cache instantly.

Matching Scryfall printings to SCG results
------------------------------------------
SCG's product URLs encode the Scryfall-compatible set code and collector
number directly:

  /lightning-bolt-sgl-mtg-3ed-162-enn/   → set=3ed  cn=162  foil=n
  /lightning-bolt-sgl-mtg-clb-187-enf/   → set=clb  cn=187  foil=f

We normalise both sides to lowercase for comparison.
"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from scraper.browser import get_browser, new_page
from scraper.disk_cache import load as disk_load, save as disk_save

logger = logging.getLogger(__name__)

BASE = "https://starcitygames.com"
_NAMESPACE = "scg"

# Per-card results cache:  card_name_lower -> list of parsed SCG items
_cache: dict[str, list[dict]] = {}
_locks: dict[str, asyncio.Lock] = {}


def search_url(card_name: str, page: int = 1) -> str:
    url = f"{BASE}/search/?search_query={quote_plus(card_name)}"
    if page > 1:
        url += f"&pg={page}"
    return url


async def get_prices(
    card_name: str,
    set_code: str,
    set_name: str,
    foil: bool,
    collector_number: str = "",
) -> dict:
    """Return SCG price/qty for one specific printing."""
    all_listings = await _get_all_for_card(card_name)
    match = _find_match(all_listings, set_code, collector_number, foil)

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
        "error":    "Not listed on SCG",
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
    all_results: list[dict] = []
    try:
        browser = await get_browser()
        page, ctx = await new_page(browser)
        try:
            for page_num in range(1, 6):  # max 5 pages
                url = search_url(card_name, page=page_num)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
                html = await page.content()
                page_results = _parse(html, card_name)
                all_results.extend(page_results)
                # If fewer than 16 results, we're on the last page
                if len(page_results) < 16:
                    break
        finally:
            await ctx.close()
    except Exception as e:
        logger.warning("SCG fetch error for '%s': %s", card_name, e)
        return []

    return all_results


def _parse(html: str, card_name: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = soup.find_all(class_="hawk-results-item")
    results = []

    for item in items:
        title_el = item.find(class_="item-title-link")
        if not title_el:
            continue

        raw_title = title_el.get_text(strip=True)
        # Normalise: strip variant subtitle like "(#117)" or "(Thrum…)"
        clean_title = re.sub(r"\s*\([^)]*\)\s*$", "", raw_title).strip()
        clean_title = re.sub(r"\s*\(Not Tournament Legal\)\s*", "", clean_title).strip()

        # Skip if clearly not the right card (e.g. double-faced with //)
        if "//" in raw_title:
            continue
        if card_name.lower() not in clean_title.lower():
            continue

        # Extract set_code and collector_number from URL slug
        href = title_el.get("href", "")
        # Pattern: /...-sgl-mtg-{set_code}-{cn}-en{n|f}/
        slug_match = re.search(r"sgl-mtg-([a-z0-9]+)-(\d+[a-z]*)-en([nf])", href, re.I)
        if not slug_match:
            continue

        slug_set   = slug_match.group(1).upper()   # e.g. "3ED"
        slug_cn    = slug_match.group(2).lstrip("0") or "0"
        is_foil    = slug_match.group(3).lower() == "f"

        # Collector number (shown on page, may have leading zeros)
        cn_el = item.find(class_="header-collector-number")
        page_cn = cn_el.get_text(strip=True).lstrip("#").lstrip("0") or "0" if cn_el else slug_cn

        # Price from data attribute (most reliable)
        variant_row = item.find(class_=re.compile(r"variant-row"))
        price_val: Optional[float] = None
        stock: Optional[int] = None

        if variant_row:
            try:
                price_val = float(variant_row.get("data-product-price", 0) or 0) or None
            except (TypeError, ValueError):
                pass
            qty_input = variant_row.find("input", class_="quantity-input")
            if qty_input:
                try:
                    stock = int(qty_input.get("max", 0))
                    if stock == 0:
                        stock = None
                except (TypeError, ValueError):
                    pass
            # Fall back to price cell text
            if price_val is None:
                price_el = item.find(class_=re.compile(r"options-table-cell--price"))
                if price_el:
                    price_txt = re.sub(r"[^\d.]", "", price_el.get_text())
                    try:
                        price_val = float(price_txt) or None
                    except ValueError:
                        pass

        full_url = BASE + href if href.startswith("/") else href

        results.append({
            "set_code":        slug_set,
            "collector_number": page_cn,
            "foil":            is_foil,
            "price":           price_val,
            "quantity":        stock,
            "url":             full_url,
        })

    return results


def _find_match(
    listings: list[dict],
    set_code: str,
    collector_number: str,
    foil: bool,
) -> Optional[dict]:
    cn = (collector_number or "").lstrip("0") or "0"
    sc = set_code.upper()

    # Pass 1: exact match — set + foil + collector number
    for item in listings:
        if item["set_code"] == sc and item["foil"] == foil and item["collector_number"] == cn:
            return item

    # Pass 2: try the raw collector number without stripping leading zeros,
    # in case SCG preserves them differently
    raw_cn = (collector_number or "").strip()
    if raw_cn and raw_cn != cn:
        for item in listings:
            if item["set_code"] == sc and item["foil"] == foil and item["collector_number"] == raw_cn:
                return item

    # Pass 3: fallback by set + foil only — but ONLY when there is exactly one
    # such listing (unambiguous old-set cards where CN isn't meaningful).
    # When multiple versions exist, skipping CN would return the wrong card.
    same_set_foil = [
        item for item in listings
        if item["set_code"] == sc and item["foil"] == foil
    ]
    if len(same_set_foil) == 1:
        return same_set_foil[0]

    return None
