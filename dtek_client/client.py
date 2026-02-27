"""Async Python client for DTEK regional disconnection-schedule sites."""

import logging
from typing import Any

import aiohttp

from .const import DTEK_SITES, DEFAULT_TIMEOUT, METHOD_GET_STREETS, METHOD_GET_HOME_NUM
from .exceptions import DtekConnectionError, DtekTimeoutError, DtekAPIError

_LOGGER = logging.getLogger(__name__)

class DtekClient:
    """Base client for fetching DTEK schedules."""

    def __init__(self, site_key: str = "kem") -> None:
        """Initialize the client."""
        if site_key not in DTEK_SITES:
            raise ValueError(f"Unknown site_key: {site_key}")
            
        self._site_key = site_key
        self._base_url, self._schedule_path = DTEK_SITES[site_key]
        self._session: aiohttp.ClientSession | None = None
        
        # Hardcoded ajax path for now. Later we will need to parse HTML or use a browser.
        self._ajax_url = f"{self._base_url}/ua/ajax"

    async def connect(self) -> None:
        """Initialize the aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                }
            )

    async def close(self) -> None:
        """Close the session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "DtekClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _request(self, method: str, data: dict[str, Any]) -> Any:
        """Make a raw POST request to the DTEK AJAX endpoint."""
        if not self._session:
            await self.connect()

        payload = {"method": method, **data}
        
        try:
            async with self._session.post(
                self._ajax_url, 
                data=payload, 
                timeout=DEFAULT_TIMEOUT
            ) as response:
                
                # NOTE: We often get 401 or 403 here because of Cloudflare/WAF.
                # Will need to figure out browser emulation later!
                if response.status != 200:
                    raise DtekAPIError(f"API returned status {response.status}")
                
                return await response.json()
                
        except TimeoutError as err:
            raise DtekTimeoutError("Request to DTEK timed out") from err
        except aiohttp.ClientError as err:
            raise DtekConnectionError("Connection to DTEK failed") from err

    async def get_streets(self, city: str) -> list[dict[str, Any]]:
        """Fetch streets for a given city. Returns raw dicts."""
        data = {"data[city]": city}
        response = await self._request(METHOD_GET_STREETS, data)
        # Assuming the API returns a list directly or inside a "data" key.
        return response.get("data", response) if isinstance(response, dict) else response

    async def get_home_num(self, city: str, street: str) -> dict[str, Any]:
        """Fetch house numbers and schedule for a street. Returns raw dict."""
        data = {
            "data[city]": city,
            "data[street]": street,
        }
        return await self._request(METHOD_GET_HOME_NUM, data)