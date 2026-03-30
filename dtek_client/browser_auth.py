"""Playwright-based helper to bypass WAF protection on DTEK sites.

Some DTEK regional sites are protected by Incapsula/Imperva WAF which issues
a JavaScript challenge to headless HTTP clients.  This module launches a real
Chromium browser (headless) via Playwright, waits for the WAF challenge to
resolve, and then extracts the session cookies and CSRF token needed for
subsequent AJAX requests.

Usage::

    from dtek_client.browser_auth import get_cleared_cookies

    cookies, csrf_token = await get_cleared_cookies(
        "https://www.dtek-krem.com.ua/ua/shutdowns"
    )
"""
from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from .exceptions import DtekConnectionError

_LOGGER = logging.getLogger(__name__)


async def get_cleared_cookies(url: str) -> tuple[dict[str, str], str | None]:
    """Launch a headless browser, wait for the WAF challenge to clear, and
    return a tuple of ``(cookies, csrf_token)``.

    Args:
        url: the schedule page URL (e.g. "https://www.dtek-krem.com.ua/ua/shutdowns").

    Returns:
        A tuple of:
            - ``cookies`` – dict of cookie name → value, ready to pass to curl_cffi.
            - ``csrf_token`` – the Yii2 CSRF token from the page meta tag, or None.
    """
    _LOGGER.info("Launching Playwright to bypass WAF for %s...", url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        _LOGGER.debug("Navigating to %s", url)
        try:
            await page.goto(url, wait_until="networkidle")
        except PlaywrightError as e:
            await browser.close()
            raise DtekConnectionError(f"Failed to load page to bypass WAF: {e}") from e

        # Allow extra time for the WAF JS challenge to complete.
        _LOGGER.debug("Waiting for WAF JS challenge to resolve...")
        await asyncio.sleep(4)

        # Extract the Yii2 CSRF token from the page meta tag.
        csrf_token = await page.get_attribute('meta[name="csrf-token"]', "content")
        if csrf_token:
            _LOGGER.info("Successfully extracted CSRF token.")
        else:
            _LOGGER.warning("CSRF token not found on the page.")

        cookies = await context.cookies()
        await browser.close()

    session_cookies = {c["name"]: c["value"] for c in cookies}
    return session_cookies, csrf_token
