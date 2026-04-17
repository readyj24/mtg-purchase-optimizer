"""Scryfall API client for fetching card printings and reference prices."""

import asyncio
import logging
from typing import Optional

import httpx

from models import CardPrinting

logger = logging.getLogger(__name__)

SCRYFALL_BASE = "https://api.scryfall.com"

# Simple in-memory cache so repeated lookups during a session are fast
_printing_cache: dict[str, list[CardPrinting]] = {}


async def search_all_printings(card_name: str) -> list[CardPrinting]:
    """Return all paper printings of a card, oldest first."""
    cache_key = card_name.lower().strip()
    if cache_key in _printing_cache:
        return _printing_cache[cache_key]

    printings: list[CardPrinting] = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        url = f"{SCRYFALL_BASE}/cards/search"
        params: Optional[dict] = {
            "q": f'!"{card_name}"',
            "unique": "prints",
            "order": "released",
            "dir": "asc",
        }

        while url:
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                # Card not found
                break
            resp.raise_for_status()
            data = resp.json()

            for card in data.get("data", []):
                # Skip digital-only (MTGO/Arena)
                if card.get("digital", False):
                    continue
                # Skip cards with no paper printing marker
                if "paper" not in card.get("games", ["paper"]):
                    continue

                image_uri = _extract_image(card)
                tcg_price = _extract_tcg_price(card, foil=False)
                tcg_foil_price = _extract_tcg_price(card, foil=True)

                base = dict(
                    card_name=card["name"],
                    set_code=card["set"].upper(),
                    set_name=card["set_name"],
                    collector_number=card["collector_number"],
                    image_uri=image_uri,
                    released_at=card.get("released_at", ""),
                    rarity=card.get("rarity", ""),
                )

                if card.get("nonfoil", True):
                    printings.append(
                        CardPrinting(
                            scryfall_id=card["id"],
                            foil=False,
                            tcg_price=tcg_price,
                            **base,
                        )
                    )

                if card.get("foil", False):
                    printings.append(
                        CardPrinting(
                            scryfall_id=card["id"] + "_foil",
                            foil=True,
                            tcg_price=tcg_foil_price,
                            **base,
                        )
                    )

            has_more = data.get("has_more", False)
            next_page = data.get("next_page")
            if has_more and next_page:
                url = next_page
                params = None
                await asyncio.sleep(0.1)  # be polite to Scryfall
            else:
                url = None

    _printing_cache[cache_key] = printings
    return printings


def _extract_image(card: dict) -> Optional[str]:
    if "image_uris" in card:
        return card["image_uris"].get("normal") or card["image_uris"].get("small")
    if "card_faces" in card:
        face = card["card_faces"][0]
        if "image_uris" in face:
            return face["image_uris"].get("normal") or face["image_uris"].get("small")
    return None


def _extract_tcg_price(card: dict, foil: bool) -> Optional[float]:
    prices = card.get("prices", {})
    key = "usd_foil" if foil else "usd"
    val = prices.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
