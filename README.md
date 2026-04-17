# MTG Purchase Optimizer

A local web app that helps you build the cheapest shopping cart for a Magic: The Gathering card list by comparing prices across **Card Kingdom**, **Star City Games**, and **Channel Fireball / TCGPlayer**.

## How it works

1. **Paste** a card list (standard formats: `4 Lightning Bolt`, `4x Sol Ring`, `1 Black Lotus (LEA)`)
2. **Review** every printing of each card — thumbnails, set, year, and live prices from all three stores load inline
3. **Exclude** any printings you don't want (e.g. too old, wrong art)
4. Get an **optimized cart** per store that minimises total cost

Prices are fetched live via Playwright (SCG, TCGPlayer) and MTGJSON (Card Kingdom), then cached to disk for 24 hours so repeat runs are instant.

## Prerequisites

- Python 3.11+
- A Chromium-compatible browser install for Playwright

## Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install Playwright's Chromium browser
python -m playwright install chromium
```

## Running

**Windows:** double-click `start.bat`

**Any platform:**
```bash
python main.py
```

Then open **http://localhost:8000** in your browser.

## Project structure

```
main.py              FastAPI backend + card list parser
optimizer.py         Greedy cheapest-price cart builder
models.py            Pydantic request/response models
scraper/
  scryfall.py        Card printings + images (Scryfall API)
  card_kingdom.py    CK prices via MTGJSON
  star_city_games.py SCG prices via Playwright
  channel_fireball.py  TCGPlayer prices via Playwright
  browser.py         Shared singleton Playwright browser
  disk_cache.py      24-hour disk cache for Playwright results
  mtgjson.py         Set file → MTGJSON UUID lookup
  prices_cache.py    AllPricesToday.json daily download
static/
  index.html / app.js / styles.css   Single-page frontend
```

## Notes

- **Windows only** at the moment — uses `WindowsProactorEventLoopPolicy` required by Playwright on Windows. Pull requests for cross-platform support welcome.
- Prices are scraped/fetched for personal use. Check each store's terms of service before deploying publicly.
- The `.cache/` directory is gitignored; it's created automatically on first run.
