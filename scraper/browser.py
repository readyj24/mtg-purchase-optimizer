"""Singleton Playwright browser shared across all store scrapers.

Launching a browser is expensive (~1–2 s).  We launch once on first use
and keep it alive for the session.  FastAPI's lifespan hook shuts it down
on exit.
"""
import asyncio
import logging
from typing import Optional

from playwright.async_api import async_playwright, Browser, Playwright

logger = logging.getLogger(__name__)

_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_lock = asyncio.Lock()

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Injected into every new page to suppress the webdriver flag
STEALTH = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    window.chrome = {runtime: {}};
"""


async def get_browser() -> Browser:
    global _playwright, _browser
    if _browser and _browser.is_connected():
        return _browser
    async with _lock:
        if _browser and _browser.is_connected():
            return _browser
        logger.info("Launching Playwright Chromium browser…")
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        logger.info("Browser launched.")
        return _browser


async def new_page(browser: Browser):
    ctx = await browser.new_context(
        user_agent=UA,
        viewport={"width": 1280, "height": 900},
    )
    page = await ctx.new_page()
    await page.add_init_script(STEALTH)
    return page, ctx


async def shutdown():
    global _playwright, _browser
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None
    logger.info("Browser shut down.")
