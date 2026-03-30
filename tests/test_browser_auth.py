"""Unit tests for dtek_client.browser_auth.

Playwright is mocked entirely — no real browser is launched.
Each test verifies one observable behaviour of get_cleared_cookies().
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dtek_client.browser_auth import get_cleared_cookies

from playwright.async_api import Error as PlaywrightError
from dtek_client.exceptions import DtekConnectionError

# ── Fixture helpers ───────────────────────────────────────────────────────────


def _make_playwright_stack(
    csrf_token: str | None = "test-csrf-token",
    cookies: list[dict] | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Return (pw_context_manager, page, browser_context, browser).

    Every async method is replaced with AsyncMock so tests can await them
    and inspect call arguments without touching the real Playwright API.
    """
    if cookies is None:
        cookies = [
            {"name": "visid_incap_1", "value": "abc123"},
            {"name": "sessionid", "value": "sess_xyz"},
        ]

    page = MagicMock()
    page.goto = AsyncMock()
    page.get_attribute = AsyncMock(return_value=csrf_token)

    browser_context = MagicMock()
    browser_context.new_page = AsyncMock(return_value=page)
    browser_context.cookies = AsyncMock(return_value=cookies)

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=browser_context)
    browser.close = AsyncMock()

    chromium = MagicMock()
    chromium.launch = AsyncMock(return_value=browser)

    playwright = MagicMock()
    playwright.chromium = chromium

    pw_cm = MagicMock()
    pw_cm.__aenter__ = AsyncMock(return_value=playwright)
    pw_cm.__aexit__ = AsyncMock(return_value=None)

    return pw_cm, page, browser_context, browser


# ── Return-value contract ─────────────────────────────────────────────────────


class TestReturnValues:
    async def test_csrf_token_is_returned_when_found(self) -> None:
        """get_cleared_cookies returns the CSRF token extracted from the
        <meta name="csrf-token"> tag when it is present on the page."""
        pw_cm, *_ = _make_playwright_stack(csrf_token="prod-csrf-abc")

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            _, csrf = await get_cleared_cookies("https://www.dtek-krem.com.ua/ua/shutdowns")

        assert csrf == "prod-csrf-abc"

    async def test_csrf_token_is_none_when_meta_tag_absent(self) -> None:
        """When the page has no csrf-token meta tag (e.g. WAF challenge page),
        csrf_token is None and no exception is raised."""
        pw_cm, *_ = _make_playwright_stack(csrf_token=None)

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            _, csrf = await get_cleared_cookies("https://example.com")

        assert csrf is None

    async def test_cookies_returned_as_name_value_dict(self) -> None:
        """Cookies from the browser context are flattened into a plain
        {name: value} dict ready to be passed to curl_cffi."""
        pw_cm, *_ = _make_playwright_stack(
            cookies=[
                {"name": "incap_ses_1", "value": "sess_val"},
                {"name": "PHPSESSID", "value": "php_val"},
            ]
        )

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            cookies, _ = await get_cleared_cookies("https://example.com")

        assert cookies == {"incap_ses_1": "sess_val", "PHPSESSID": "php_val"}

    async def test_empty_cookie_jar_returns_empty_dict(self) -> None:
        """If the browser accumulates no cookies (unusual but valid), the
        returned dict is empty rather than None or an error."""
        pw_cm, *_ = _make_playwright_stack(cookies=[])

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            cookies, _ = await get_cleared_cookies("https://example.com")

        assert cookies == {}

    async def test_return_type_is_tuple_of_dict_and_optional_str(self) -> None:
        """The return type contract: (dict[str, str], str | None)."""
        pw_cm, *_ = _make_playwright_stack()

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            result = await get_cleared_cookies("https://example.com")

        cookies, csrf = result
        assert isinstance(cookies, dict)
        assert csrf is None or isinstance(csrf, str)


# ── Playwright interaction contract ───────────────────────────────────────────


class TestPlaywrightInteractions:
    async def test_browser_launched_in_headless_mode(self) -> None:
        """Chromium must always be launched headless so the helper can run
        on CI servers and Docker containers without a display."""
        pw_cm, _, _, _ = _make_playwright_stack()

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            await get_cleared_cookies("https://example.com")

        pw_cm.__aenter__.return_value.chromium.launch.assert_awaited_once_with(headless=True)

    async def test_page_navigates_to_the_provided_url(self) -> None:
        """page.goto must be called with the exact URL supplied by the caller
        and wait_until='networkidle' so the WAF challenge has time to resolve."""
        pw_cm, page, _, _ = _make_playwright_stack()
        url = "https://www.dtek-krem.com.ua/ua/shutdowns"

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            await get_cleared_cookies(url)

        page.goto.assert_awaited_once_with(url, wait_until="networkidle")

    async def test_csrf_extracted_from_correct_meta_selector(self) -> None:
        """get_attribute must query exactly meta[name="csrf-token"] / "content"
        so that a differently-named tag does not silently return the wrong value."""
        pw_cm, page, _, _ = _make_playwright_stack()

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            await get_cleared_cookies("https://example.com")

        page.get_attribute.assert_awaited_once_with('meta[name="csrf-token"]', "content")

    async def test_waf_delay_is_awaited_once(self) -> None:
        """asyncio.sleep(4) is called once to give the Incapsula/Imperva
        JS challenge enough time to complete before cookies are collected."""
        pw_cm, *_ = _make_playwright_stack()
        sleep_mock = AsyncMock()

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=sleep_mock),
        ):
            await get_cleared_cookies("https://example.com")

        sleep_mock.assert_awaited_once_with(4)

    async def test_browser_is_closed_after_successful_run(self) -> None:
        """browser.close() must always be awaited so no Chromium process is
        leaked even when the helper completes without errors."""
        pw_cm, _, _, browser = _make_playwright_stack()

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            await get_cleared_cookies("https://example.com")

        browser.close.assert_awaited_once()

    async def test_raises_dtek_connection_error_on_playwright_failure(self) -> None:
        """If page.goto raises PlaywrightError (e.g., no internet or DNS failure),
        the browser must be cleanly closed and DtekConnectionError raised."""
        pw_cm, page, _, browser = _make_playwright_stack()

        # Simulate the absence of the Internet — force page.goto to throw an error
        error_msg = "net::ERR_NAME_NOT_RESOLVED"
        page.goto.side_effect = PlaywrightError(error_msg)

        with (
            patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm),
            patch("dtek_client.browser_auth.asyncio.sleep", new=AsyncMock()),
        ):
            # Verify that the script will throw our error with the correct text
            with pytest.raises(
                DtekConnectionError, match=f"Failed to load page to bypass WAF: {error_msg}"
            ):
                await get_cleared_cookies("https://example.com")

        # Let's check that we didn't forget to close the browser before throwing an error!
        browser.close.assert_awaited_once()
