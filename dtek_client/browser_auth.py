"""Optional Playwright-based helper to clear WAF challenges on DTEK sites.

Normal AJAX requests to ``/ua/ajax`` work directly via Yii2 CSRF cookies
without a browser. This module is provided as an optional fallback
(``pip install dtek-blackout-client[browser]``) for environments where
full HTML page cookies must be harvested through Chromium.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from .exceptions import DtekConnectionError

_LOGGER = logging.getLogger(__name__)
_IMPORT_ERROR: ImportError | None = None

async_playwright: Any
Stealth: Any
PlaywrightError: type[Exception]

try:
    from playwright.async_api import Error as _PlaywrightError
    from playwright.async_api import async_playwright as _async_playwright
    from playwright_stealth import Stealth as _Stealth
except ImportError as exc:
    PlaywrightError = Exception
    async_playwright = None
    Stealth = None
    _IMPORT_ERROR = exc
else:
    PlaywrightError = _PlaywrightError
    async_playwright = _async_playwright
    Stealth = _Stealth

DEFAULT_BROWSER_USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_NAVIGATION_TIMEOUT_MS: Final = 60000


async def get_cleared_cookies(
    url: str,
    show_browser: bool = False,
    *,
    user_agent: str = DEFAULT_BROWSER_USER_AGENT,
) -> tuple[dict[str, str], str | None]:
    """Launch Chromium, wait for the WAF challenge to clear, and return cookies and CSRF token.

    Args:
        url: Schedule page URL (e.g. "https://www.dtek-krem.com.ua/ua/shutdowns").
        show_browser: Launch a visible browser window for manual verification when True.
        user_agent: User-Agent string configured on the browser context.

    Returns:
        Tuple of ``(cookies_dict, csrf_token)``.

    Raises:
        ImportError: If optional browser dependencies are not installed.
        DtekConnectionError: If Playwright fails to load the target page.
    """
    if async_playwright is None or Stealth is None:
        raise ImportError(
            "Playwright is required for browser_auth. "
            "Install optional browser dependencies with: pip install dtek-blackout-client[browser]"
        ) from _IMPORT_ERROR

    _LOGGER.info("Launching Playwright to bypass WAF for %s", url)

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=not show_browser)
        context = await browser.new_context(user_agent=user_agent)
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)
        except PlaywrightError as exc:
            await browser.close()
            raise DtekConnectionError(f"Failed to load page to bypass WAF: {exc}") from exc

        if show_browser:
            _LOGGER.info("Waiting for manual verification in the browser window")
        try:
            await page.wait_for_selector(
                'meta[name="csrf-token"]',
                state="attached",
                timeout=_NAVIGATION_TIMEOUT_MS,
            )
            _LOGGER.info("Page loaded and WAF challenge cleared")
        except PlaywrightError:
            _LOGGER.warning("Timeout waiting for csrf-token meta tag after challenge")

        try:
            csrf_token = await page.get_attribute('meta[name="csrf-token"]', "content")
        except PlaywrightError:
            csrf_token = None

        cookies = await context.cookies()
        await browser.close()

    session_cookies = {c["name"]: c["value"] for c in cookies}
    return session_cookies, csrf_token
