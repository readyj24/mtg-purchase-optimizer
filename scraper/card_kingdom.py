"""Card Kingdom price fetcher.

Card Kingdom's website is behind Cloudflare so direct HTTP scraping is
blocked.  We pull prices from MTGJSON's AllPricesToday.json (cached
daily on disk) using the MTGJSON UUID resolved from the set file.
"""

import logging
from urllib.parse import quote_plus
from typing import Optional

from scraper.mtgjson import get_uuid
from scraper.prices_cache import get_prices_for_uuid

logger = logging.getLogger(__name__)

BASE = "https://www.cardkingdom.com"


def search_url(card_name: str) -> str:
    return f"{BASE}/catalog/search?search=mt&filter[name]={quote_plus(card_name)}"


async def get_prices(
    card_name: str,
    set_code: str,
    set_name: str,
    foil: bool,
    collector_number: str = "",
) -> dict:
    """Return Card Kingdom retail price via MTGJSON AllPricesToday."""
    link = search_url(card_name)
    price: Optional[float] = None
    error: Optional[str] = None

    try:
        uuid = await get_uuid(set_code, collector_number)
        if not uuid:
            error = "Card not found in MTGJSON set data"
        else:
            store_prices = await get_prices_for_uuid(uuid)
            ck = store_prices.get("cardkingdom", {})
            price = ck.get("foil" if foil else "normal")
            if price is None:
                error = "No Card Kingdom price in today's MTGJSON data"
    except Exception as e:
        logger.warning("CK price lookup failed for %s %s: %s", card_name, set_code, e)
        error = str(e)

    return {
        "price": price,
        "quantity": None,   # MTGJSON doesn't include stock levels
        "url": link,
        "condition": "NM",
        "error": error,
    }
