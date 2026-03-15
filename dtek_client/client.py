"""Async Python client for DTEK regional disconnection-schedule sites."""

import logging
from typing import Any

from curl_cffi.requests import AsyncSession

from .const import DTEK_SITES, DEFAULT_TIMEOUT, METHOD_GET_STREETS, METHOD_GET_HOME_NUM
from .exceptions import (
    DtekConnectionError, 
    DtekTimeoutError, 
    DtekAPIError,
    DtekUnauthorizedError,
    DtekRateLimitError,
    DtekNotFoundError
)
from .models import StreetSuggestion, HomeNumResponse, AddressResult

_LOGGER = logging.getLogger(__name__)

class DtekClient:
    """Base client for fetching DTEK schedules."""

    def __init__(
        self, 
        site_key: str = "kem",
        ajax_url: str | None = None,
        session: AsyncSession | None = None
    ) -> None:
        if site_key not in DTEK_SITES:
            raise ValueError(f"Unknown site_key: {site_key}")
            
        self._site_key = site_key
        self._base_url, self._schedule_path = DTEK_SITES[site_key]
        
        # Дозволяємо передавати готову сесію ззовні (як у manual_test.py)
        self._session = session
        self._owns_session = session is None
        self._ajax_url = ajax_url or f"{self._base_url}/ua/ajax"

    async def connect(self) -> None:
        """Initialize session and do a warmup GET request."""
        if self._session is None:
            self._session = AsyncSession(
                timeout=DEFAULT_TIMEOUT,
                impersonate="chrome120",  # Нативна імітація Chrome!
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{self._base_url}{self._schedule_path}",
                }
            )
            # Прогрівочний запит для отримання базових WAF-кук
            try:
                await self._session.get(f"{self._base_url}{self._schedule_path}")
            except Exception as e:
                raise DtekConnectionError(f"Failed to connect: {e}")

    async def close(self) -> None:
        """Close the session."""
        if self._session and self._owns_session:
            self._session.close()
            self._session = None

    async def __aenter__(self) -> "DtekClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
        
    async def _request(self, method: str, data: dict[str, Any]) -> Any:
        if not self._session:
            await self.connect()

        payload = {"method": method, **data}

        try:
            response = await self._session.post(
                self._ajax_url, 
                data=payload, 
            )
            
            # У curl_cffi використовується status_code замість status
            if response.status_code in (401, 403):
                raise DtekUnauthorizedError(f"Access denied: {response.status_code}. WAF block.")
            if response.status_code != 200:
                raise DtekAPIError(f"API returned status {response.status_code}. Body: {response.text}")
            
            # У curl_cffi .json() — це синхронний метод, await не потрібен
            return response.json()
        except Exception as e:
            _LOGGER.error("Request failed: %s", e)
            raise

    async def get_streets(self, city: str) -> list[StreetSuggestion]:
        """Fetch streets for a given city and return a list of StreetSuggestion objects."""
        # Використовуємо формат jQuery serializeArray
        data = {
            "data[0][name]": "city",
            "data[0][value]": city,
        }
        response = await self._request(METHOD_GET_STREETS, data)

        # Обробляємо різні формати відповіді (список або словник)
        raw_streets = []
        if isinstance(response, dict):
            # Витягуємо дані з ключа 'streets' або 'data'
            raw_data = response.get("streets", response.get("data", {}))
            if isinstance(raw_data, dict):
                # Якщо прийшов словник списків, розгортаємо його в один список
                for group in raw_data.values():
                    if isinstance(group, list):
                        raw_streets.extend(group)
                    else:
                        raw_streets.append(group)
            elif isinstance(raw_data, list):
                # Якщо прийшов список списків
                for item in raw_data:
                    if isinstance(item, list):
                        raw_streets.extend(item)
                    else:
                        raw_streets.append(item)

        # Перетворюємо назви вулиць (рядки) на об'єкти StreetSuggestion і прибираємо дублікати
        unique_names = sorted(list(set(str(s) for s in raw_streets if s)))
        return [StreetSuggestion(name=name) for name in unique_names]

    async def get_home_num(
        self,
        city: str,
        street: str,
    ) -> HomeNumResponse:
        """Fetch houses and schedules, returning a validated HomeNumResponse object."""
        data = {
            "data[0][name]": "city",
            "data[0][value]": city,
            "data[1][name]": "street",
            "data[1][value]": street,
        }
        
        # Отримуємо сирий словник
        response = await self._request(METHOD_GET_HOME_NUM, data)
        
        # Перетворюємо його на об'єкт моделі
        return HomeNumResponse.model_validate(response)
    
    
    async def get_group_by_address(
        self,
        city: str,
        street: str,
        house_number: str,
    ) -> AddressResult:
        """Find the disconnection group for a specific address."""
        response = await self.get_home_num(city, street)

        entry = response.houses.get(house_number)
        if entry is None:
            raise DtekNotFoundError(
                f"House {house_number!r} not found on {street!r}, {city!r}. "
                f"Available numbers: {', '.join(sorted(response.houses.keys()))}"
            )

        group_id = entry.primary_group or "unknown"
        group_name = ""
        if response.preset and group_id in response.preset.sch_names:
            group_name = response.preset.sch_names[group_id]

        return AddressResult(
            site_key=self._site_key,
            city=city,
            street=street,
            house_number=house_number,
            group_id=group_id,
            group_display_name=group_name,
        )

    async def get_today_schedule(
        self,
        city: str,
        street: str,
        house_number: str,
    ) -> dict[str, Any] | None:
        """Shortcut: return today's fact-schedule slot map for one house."""
        response = await self.get_home_num(city, street)
        entry = response.houses.get(house_number)
        
        if entry is None or not entry.primary_group:
            return None

        if response.fact is None:
            return None

        return response.fact.get_group_today(entry.primary_group)