"""Playwright-based helper to bypass WAF protection on DTEK sites."""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional, Tuple

from playwright.async_api import async_playwright, Error as PlaywrightError
from .exceptions import DtekConnectionError

_LOGGER = logging.getLogger(__name__)


async def get_cleared_cookies(url: str) -> Tuple[Dict[str, str], Optional[str]]:
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
            raise DtekConnectionError(f"Failed to load page to bypass WAF: {e}")

        _LOGGER.debug("Waiting for WAF JS challenge to resolve...")
        await asyncio.sleep(4)

        csrf_token = await page.get_attribute('meta[name="csrf-token"]', "content")
        if csrf_token:
            _LOGGER.info("Successfully extracted CSRF token.")
        else:
            _LOGGER.warning("CSRF token not found on the page.")

        cookies = await context.cookies()
        await browser.close()

    session_cookies = {c["name"]: c["value"] for c in cookies}
    return session_cookies, csrf_token
