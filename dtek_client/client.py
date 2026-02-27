"""Async Python client for DTEK regional disconnection-schedule sites."""

import logging
from typing import Any

import aiohttp

# Імпортуємо саме функцію, яка є у файлі
from .browser_auth import get_cleared_cookies
from .const import DTEK_SITES, DEFAULT_TIMEOUT, METHOD_GET_STREETS, METHOD_GET_HOME_NUM
from .exceptions import (
    DtekConnectionError, 
    DtekTimeoutError, 
    DtekAPIError,
    DtekUnauthorizedError,
    DtekRateLimitError
)

_LOGGER = logging.getLogger(__name__)

class DtekClient:
    """Base client for fetching DTEK schedules."""

    def __init__(self, site_key: str = "kem") -> None:
        if site_key not in DTEK_SITES:
            raise ValueError(f"Unknown site_key: {site_key}")
            
        self._site_key = site_key
        self._base_url, self._schedule_path = DTEK_SITES[site_key]
        self._session: aiohttp.ClientSession | None = None
        
        self._ajax_url = f"{self._base_url}/ua/ajax"
        self._csrf_token: str | None = None

    async def connect(self) -> None:
        """Initialize session and bypass WAF using Playwright function."""
        if self._session is None:
            target_url = f"{self._base_url}{self._schedule_path}"
            cookies_dict, csrf = await get_cleared_cookies(target_url)
            
            self._csrf_token = csrf
            
            self._session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": target_url,
                }
            )
            
            # Фільтруємо куки, щоб aiohttp не впав через криві імена від Cloudflare/WordPress
            reserved_keys = {"expires", "path", "comment", "domain", "max-age", "secure", "httponly", "version", "samesite"}
            safe_cookies = {
                name: value 
                for name, value in cookies_dict.items() 
                if name.lower() not in reserved_keys
            }
            
            self._session.cookie_jar.update_cookies(safe_cookies)
        
    async def close(self) -> None:
        """Close the session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "DtekClient":
        """Enter the async context manager."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the async context manager and close the session."""
        await self.close()
        
    async def _request(self, method: str, data: dict[str, Any]) -> Any:
        if not self._session:
            await self.connect()

        payload = {"method": method, **data}
        
        headers = {}
        if self._csrf_token:
            headers["X-CSRF-TOKEN"] = self._csrf_token

        try:
            async with self._session.post(
                self._ajax_url, 
                data=payload, 
                headers=headers,
                timeout=DEFAULT_TIMEOUT
            ) as response:
                
                if response.status in (401, 403):
                    raise DtekUnauthorizedError(f"Access denied: {response.status}. WAF is still blocking us.")
                if response.status != 200:
                    # Якщо 400 — можливо, ми не додали якийсь обов'язковий параметр AJAX
                    raise DtekAPIError(f"API returned status {response.status}. Body: {await response.text()}")
                
                return await response.json()
        except Exception as e:
            _LOGGER.error("Request failed: %s", e)
            raise

    async def get_streets(self, city: str) -> list[dict[str, Any]]:
        """Fetch streets for a given city. Returns raw dicts."""
        # Використовуємо формат jQuery serializeArray, який очікує сервер
        data = {
            "data[0][name]": "city",
            "data[0][value]": city,
        }
        response = await self._request(METHOD_GET_STREETS, data)
        return response.get("data", response) if isinstance(response, dict) else response

    async def get_home_num(self, city: str, street: str) -> dict[str, Any]:
        """Fetch house numbers and schedule for a street. Returns raw dict."""
        # Використовуємо формат jQuery serializeArray
        data = {
            "data[0][name]": "city",
            "data[0][value]": city,
            "data[1][name]": "street",
            "data[1][value]": street,
        }
        return await self._request(METHOD_GET_HOME_NUM, data)