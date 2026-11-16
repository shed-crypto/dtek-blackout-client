"""Unit tests for dtek_client.browser_auth."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("playwright")
pytest.importorskip("playwright_stealth")

from playwright.async_api import Error as PlaywrightError  # noqa: E402

from dtek_client.browser_auth import get_cleared_cookies  # noqa: E402
from dtek_client.exceptions import DtekConnectionError  # noqa: E402


def _make_playwright_stack(
    csrf_token: str | None = "test-csrf-token",  # noqa: S107
    cookies: list[dict[str, str]] | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Return mocked (pw_context_manager, page, browser_context, browser)."""
    if cookies is None:
        cookies = [
            {"name": "visid_incap_1", "value": "abc123"},
            {"name": "sessionid", "value": "sess_xyz"},
        ]

    page = MagicMock()
    page.goto = AsyncMock()
    page.get_attribute = AsyncMock(return_value=csrf_token)
    page.wait_for_selector = AsyncMock()

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


class TestReturnValues:
    async def test_csrf_token_is_returned_when_found(self) -> None:
        pw_cm, *_ = _make_playwright_stack(csrf_token="prod-csrf-abc")  # noqa: S106

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            _, csrf = await get_cleared_cookies("https://www.dtek-krem.com.ua/ua/shutdowns")

        assert csrf == "prod-csrf-abc"

    async def test_csrf_token_is_none_when_meta_tag_absent(self) -> None:
        pw_cm, *_ = _make_playwright_stack(csrf_token=None)

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            _, csrf = await get_cleared_cookies("https://example.com")

        assert csrf is None

    async def test_cookies_returned_as_name_value_dict(self) -> None:
        pw_cm, *_ = _make_playwright_stack(
            cookies=[
                {"name": "incap_ses_1", "value": "sess_val"},
                {"name": "PHPSESSID", "value": "php_val"},
            ]
        )

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            cookies, _ = await get_cleared_cookies("https://example.com")

        assert cookies == {"incap_ses_1": "sess_val", "PHPSESSID": "php_val"}

    async def test_empty_cookie_jar_returns_empty_dict(self) -> None:
        pw_cm, *_ = _make_playwright_stack(cookies=[])

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            cookies, _ = await get_cleared_cookies("https://example.com")

        assert cookies == {}

    async def test_return_type_is_tuple_of_dict_and_optional_str(self) -> None:
        pw_cm, *_ = _make_playwright_stack()

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            cookies, csrf = await get_cleared_cookies("https://example.com")

        assert isinstance(cookies, dict)
        assert csrf is None or isinstance(csrf, str)


class TestPlaywrightInteractions:
    async def test_browser_launched_in_headless_mode_by_default(self) -> None:
        pw_cm, _, _, _ = _make_playwright_stack()

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            await get_cleared_cookies("https://example.com")

        pw_cm.__aenter__.return_value.chromium.launch.assert_awaited_once_with(headless=True)

    async def test_browser_launched_visible_when_show_browser_true(self) -> None:
        pw_cm, _, _, _ = _make_playwright_stack()

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            await get_cleared_cookies("https://example.com", show_browser=True)

        pw_cm.__aenter__.return_value.chromium.launch.assert_awaited_once_with(headless=False)

    async def test_page_navigates_to_the_provided_url(self) -> None:
        pw_cm, page, _, _ = _make_playwright_stack()
        url = "https://www.dtek-krem.com.ua/ua/shutdowns"

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            await get_cleared_cookies(url)

        page.goto.assert_awaited_once_with(url, wait_until="domcontentloaded", timeout=60000)

    async def test_csrf_extracted_from_correct_meta_selector(self) -> None:
        pw_cm, page, _, _ = _make_playwright_stack()

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            await get_cleared_cookies("https://example.com")

        page.get_attribute.assert_awaited_once_with('meta[name="csrf-token"]', "content")

    async def test_waf_challenge_waits_for_selector(self) -> None:
        pw_cm, page, _, _ = _make_playwright_stack()

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            await get_cleared_cookies("https://example.com")

        page.wait_for_selector.assert_awaited_once_with(
            'meta[name="csrf-token"]', state="attached", timeout=60000
        )

    async def test_timeout_waiting_for_selector_continues_and_returns_cookies(self) -> None:
        pw_cm, page, _, _ = _make_playwright_stack()
        page.wait_for_selector.side_effect = PlaywrightError("Timeout 60000ms exceeded")
        page.get_attribute.side_effect = PlaywrightError("Selector not found")

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            cookies, csrf = await get_cleared_cookies("https://example.com")

        assert cookies == {"visid_incap_1": "abc123", "sessionid": "sess_xyz"}
        assert csrf is None

    async def test_browser_is_closed_after_successful_run(self) -> None:
        pw_cm, _, _, browser = _make_playwright_stack()

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            await get_cleared_cookies("https://example.com")

        browser.close.assert_awaited_once()

    async def test_raises_dtek_connection_error_on_playwright_failure(self) -> None:
        pw_cm, page, _, browser = _make_playwright_stack()
        error_msg = "net::ERR_NAME_NOT_RESOLVED"
        page.goto.side_effect = PlaywrightError(error_msg)

        with patch("dtek_client.browser_auth.async_playwright", return_value=pw_cm):
            with pytest.raises(
                DtekConnectionError, match=f"Failed to load page to bypass WAF: {error_msg}"
            ):
                await get_cleared_cookies("https://example.com")

        browser.close.assert_awaited_once()


class TestOptionalDependencyGuard:
    async def test_module_imports_and_raises_install_hint_when_playwright_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "playwright", None)
        monkeypatch.setitem(sys.modules, "playwright.async_api", None)
        monkeypatch.setitem(sys.modules, "playwright_stealth", None)

        module_path = Path(__file__).resolve().parents[1] / "dtek_client" / "browser_auth.py"
        spec = importlib.util.spec_from_file_location(
            "dtek_client._browser_auth_no_pw", module_path
        )
        assert spec is not None and spec.loader is not None
        isolated_mod = importlib.util.module_from_spec(spec)
        isolated_mod.__package__ = "dtek_client"
        spec.loader.exec_module(isolated_mod)

        assert isolated_mod.async_playwright is None
        with pytest.raises(ImportError, match=r"dtek-blackout-client\[browser\]"):
            await isolated_mod.get_cleared_cookies("https://example.com")
