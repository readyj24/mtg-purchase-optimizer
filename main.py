"""MTG Purchase Optimizer — FastAPI backend."""

import asyncio
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from typing import Optional

# Playwright requires ProactorEventLoop on Windows to launch subprocesses.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from models import CardListParseRequest, OptimizeRequest
from optimizer import optimize_cart
from scraper.browser import shutdown as browser_shutdown
from scraper.card_kingdom import get_prices as ck_prices
from scraper.channel_fireball import get_prices as cfb_prices
from scraper.scryfall import search_all_printings
from scraper.star_city_games import get_prices as scg_prices

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await browser_shutdown()


app = FastAPI(title="MTG Purchase Optimizer", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Card list parsing
# ---------------------------------------------------------------------------

def _parse_line(line: str) -> Optional[dict]:
    """Parse one line of a card list into {card_name, quantity, set_hint}."""
    line = line.strip()
    if not line or line.startswith("//") or line.startswith("#"):
        return None
    # Strip leading bullets / dashes
    line = re.sub(r"^[\s\-\*]+", "", line).strip()
    if not line:
        return None

    # Patterns tried in order:
    # "4x Lightning Bolt (M10)"  |  "4 Lightning Bolt [M10]"
    # "Lightning Bolt x4"
    # "4 Lightning Bolt"
    # "Lightning Bolt"
    patterns = [
        r"^(\d+)\s*x?\s+(.+?)(?:\s+[\(\[]([\w\d\s]+)[\)\]])?$",
        r"^(.+?)\s+x\s*(\d+)(?:\s+[\(\[]([\w\d\s]+)[\)\]])?$",
        r"^(.+)$",
    ]

    for i, pat in enumerate(patterns):
        m = re.match(pat, line, re.IGNORECASE)
        if not m:
            continue
        if i == 0:
            qty, name, set_hint = int(m.group(1)), m.group(2).strip(), m.group(3)
        elif i == 1:
            qty, name, set_hint = int(m.group(2)), m.group(1).strip(), m.group(3)
        else:
            qty, name, set_hint = 1, m.group(1).strip(), None
        name = re.sub(r"\s+", " ", name).strip()
        if name:
            return {
                "original_text": line,
                "card_name": name,
                "quantity": qty,
                "set_hint": set_hint,
            }
    return None


@app.post("/api/parse-list")
async def parse_list(req: CardListParseRequest):
    cards = []
    for line in req.text.splitlines():
        parsed = _parse_line(line)
        if parsed:
            cards.append(parsed)
    return {"cards": cards}


# ---------------------------------------------------------------------------
# Card printings (Scryfall)
# ---------------------------------------------------------------------------

@app.get("/api/card/printings")
async def get_printings(name: str):
    try:
        printings = await search_all_printings(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not printings:
        raise HTTPException(status_code=404, detail=f"No printings found for '{name}'")
    return {"printings": [p.model_dump() for p in printings], "count": len(printings)}


# ---------------------------------------------------------------------------
# Store prices
# ---------------------------------------------------------------------------

@app.post("/api/prices")
async def get_store_prices(req: dict):
    """Fetch prices from all stores in parallel for one printing."""
    card_name = req.get("card_name", "")
    set_code = req.get("set_code", "")
    set_name = req.get("set_name", "")
    collector_number = req.get("collector_number", "")
    foil = req.get("foil", False)

    ck, scg, cfb = await asyncio.gather(
        ck_prices(card_name, set_code, set_name, foil, collector_number),
        scg_prices(card_name, set_code, set_name, foil, collector_number),
        cfb_prices(card_name, set_code, set_name, foil, collector_number),
        return_exceptions=True,
    )

    def _safe(result, store_id, store_name):
        if isinstance(result, Exception):
            return {"store_id": store_id, "store_name": store_name, "price": None, "quantity": None, "url": None, "error": str(result)}
        result["store_id"] = store_id
        result["store_name"] = store_name
        return result

    return {
        "card_kingdom": _safe(ck, "card_kingdom", "Card Kingdom"),
        "star_city_games": _safe(scg, "star_city_games", "Star City Games"),
        "channel_fireball": _safe(cfb, "channel_fireball", "Channel Fireball"),
    }


# ---------------------------------------------------------------------------
# Cart optimisation
# ---------------------------------------------------------------------------

@app.post("/api/optimize")
async def optimize(req: OptimizeRequest):
    result = optimize_cart(req)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run("main:app", host=host, port=port, reload=False)
