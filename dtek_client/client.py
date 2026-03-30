"""Async HTTP client for DTEK regional disconnection-schedule sites.

Architecture
------------
DTEK regional sites (e.g. dtek-kem.com.ua, dtek-krem.com.ua) are WordPress
applications. They have no public REST API; the frontend communicates with the
server through an AJAX endpoint whose URL is embedded in the schedule page as:

    <meta name="ajaxUrl" content="https://...">

Note: the meta content may be a relative path ("/ua/ajax"). In that case
the client prepends base_url automatically.

This client:
  1. Fetches the schedule page (tries several paths) and extracts ajaxUrl (cached).
  2. Sends form-encoded AJAX requests (method=getStreets / getHomeNum).
  3. Parses responses into Pydantic models.

Quick start::

    async with DtekClient("krem") as client:
        streets = await client.get_streets("м. Українка")
        result  = await client.get_group_by_address(
            city="м. Українка",
            street="вул. Юності",
            house_number="10",
        )
        print(result)
"""
from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import Any
from urllib.parse import urljoin, urlparse

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.errors import RequestsError
from pydantic import ValidationError

from .const import (
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_RETRY_DELAY,
    DEFAULT_SITE_KEY,
    DEFAULT_TIMEOUT,
    DTEK_SITES,
    FALLBACK_AJAX_PATH,
    HTTP_NOT_FOUND,
    HTTP_SERVER_ERROR,
    HTTP_TOO_MANY_REQUESTS,
    HTTP_UNAUTHORIZED,
    META_AJAX_URL,
    METHOD_GET_HOME_NUM,
    METHOD_GET_STREETS,
    SCHEDULE_PAGE_FALLBACK_PATHS,
)
from .exceptions import (
    DtekAPIError,
    DtekConnectionError,
    DtekDataError,
    DtekNotFoundError,
    DtekRateLimitError,
    DtekServerError,
    DtekSiteError,
    DtekUnauthorizedError,
)
from .models import AddressResult, HomeNumResponse, StreetSuggestion

__all__ = ["DtekClient"]
_LOGGER = logging.getLogger(__name__)

# ── ajaxUrl discovery patterns ────────────────────────────────────────────────
# Pattern 1 & 2: <meta name="ajaxUrl" content="..."> (both attribute orderings)
_META_RE = re.compile(
    r'<meta\s[^>]*name=["\']' + META_AJAX_URL + r'["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_META_RE2 = re.compile(
    r'<meta\s[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']' + META_AJAX_URL + r'["\']',
    re.IGNORECASE,
)
# Pattern 3: var ajaxUrl = "...";
_JS_VAR_RE = re.compile(
    r'var\s+ajaxUrl\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Pattern 4: wp_localize_script / inline JS object  {"ajaxUrl":"..."}
_JS_OBJ_RE = re.compile(
    r'["\']ajaxUrl["\']\s*:\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Pattern 5: WordPress standard  {"ajax_url":"..."}
_WP_AJAX_RE = re.compile(
    r'["\']ajax_url["\']\s*:\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

_AJAX_PATTERNS = [_META_RE, _META_RE2, _JS_VAR_RE, _JS_OBJ_RE, _WP_AJAX_RE]

# Markers that identify an Incapsula/Imperva WAF JavaScript challenge page.
_INCAPSULA_MARKERS = ("_Incapsula_Resource", "visid_incap", "incap_ses")


def _resolve_ajax_url(raw: str, base_url: str) -> str:
    """Resolve an ajaxUrl that may be a relative path.

    DTEK sites sometimes return a relative path in <meta name="ajaxUrl">,
    e.g. content="/ua/ajax".  This function converts it to an absolute URL.

    Examples::

        "/ua/ajax"           + "https://www.dtek-krem.com.ua" → "https://www.dtek-krem.com.ua/ua/ajax"
        "https://..."        + any                             → "https://..."  (unchanged)
        "/ua/register/ajax"  + "https://www.dtek-krem.com.ua" → "https://www.dtek-krem.com.ua/ua/register/ajax"
    """
    raw = raw.replace("\\/", "/").strip()
    parsed = urlparse(raw)
    if parsed.scheme:
        # Already a fully-qualified URL (http:// or https://).
        return raw
    # Relative path — join with base_url.
    return urljoin(base_url, raw)


class DtekClient:
    """Asynchronous client for DTEK regional disconnection-schedule sites.

    Args:
        site_key: one of the keys defined in ``DTEK_SITES``
                  (e.g. ``"kem"``, ``"krem"``, ``"oem"`` …).
                  Defaults to ``"kem"`` (DTEK Kyivenerho).
        ajax_url: if provided, skip the meta-tag discovery step and use this
                  URL directly for AJAX requests.  Useful for testing or when
                  the site is behind a WAF and you have the URL from DevTools.
        timeout: per-request timeout in seconds.
        retry_attempts: number of retries on transient 5xx errors.
        retry_delay: seconds between retries (linear back-off).
        session: inject an existing ``curl_cffi.requests.AsyncSession``.
                 In Home Assistant, pass the result of ``async_get_clientsession(hass)``
                 wrapped in an adapter, or let the client create its own session.
    """

    def __init__(
        self,
        site_key: str = DEFAULT_SITE_KEY,
        *,
        ajax_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        session: AsyncSession | None = None,
    ) -> None:
        if site_key not in DTEK_SITES:
            raise DtekSiteError(
                f"Unknown site_key {site_key!r}. "
                f"Valid options: {sorted(DTEK_SITES.keys())}"
            )

        self._site_key = site_key
        self._base_url, self._schedule_path = DTEK_SITES[site_key]
        self._ajax_url: str | None = ajax_url
        self._timeout = timeout
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay
        self._session: AsyncSession | None = session
        # True when the client owns the session and must close it on exit.
        self._owns_session: bool = session is None
        # Cache for the global schedule fetched via checkDisconUpdate.
        self._global_schedule: dict[str, Any] | None = None

    # ── Session lifecycle ─────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open a curl_cffi session (no-op if a session was injected)."""
        if self._session is None:
            headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "uk,en-US;q=0.9,en;q=0.8",
                "Origin": self._base_url,
                "Referer": f"{self._base_url}/ua/shutdowns",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
            self._session = AsyncSession(
                timeout=self._timeout,
                headers=headers,
                impersonate="chrome120",
            )
            # Perform a warm-up GET to acquire WAF session cookies before
            # making POST requests.  Incapsula returns HTTP 400 without this.
            try:
                _LOGGER.debug("Fetching initial WAF cookies from %s", self._base_url)
                await self._session.get(f"{self._base_url}/ua/shutdowns")
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("Warm-up GET failed (non-fatal): %s", exc)

    async def close(self) -> None:
        """Close the session (only if this client created it)."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> DtekClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # ── ajaxUrl discovery ─────────────────────────────────────────────────────

    async def _fetch_page_html(self, path: str) -> str | None:
        """Fetch a schedule page and return its HTML, or None on 404 / WAF block."""
        url = f"{self._base_url}{path}"
        try:
            resp = await self._session.get(url)  # type: ignore[union-attr]
            if resp.status_code == HTTP_NOT_FOUND:
                _LOGGER.debug("Schedule path %s → 404, trying next.", path)
                return None
            if resp.status_code >= HTTP_SERVER_ERROR:
                raise DtekServerError(resp.status_code)
            html: str = resp.text
        except RequestsError as exc:
            raise DtekConnectionError(f"Cannot reach {url}: {exc}") from exc

        # Detect Incapsula/Imperva WAF JavaScript challenge (~800 bytes).
        if any(marker in html for marker in _INCAPSULA_MARKERS):
            _LOGGER.warning(
                "Incapsula/Imperva WAF challenge detected on %s "
                "(page is %d chars — the real site is typically 100 KB+). "
                "Automatic ajaxUrl discovery is blocked. "
                "Fix: open the schedule page in a real browser, locate "
                '<meta name="ajaxUrl"> and pass the URL as ajax_url= to DtekClient().',
                url,
                len(html),
            )
            return None  # Treat as not found — fall through to the next path.

        return html

    async def _get_ajax_url(self) -> str:
        """Return the ajaxUrl, discovering it from the schedule page if needed.

        Discovery strategy (in priority order):

        1. Already cached from a previous call.
        2. Try the primary schedule_path from DTEK_SITES.
        3. Try fallback paths from SCHEDULE_PAGE_FALLBACK_PATHS.
        4. If nothing is found — use the hardcoded fallback: base_url + /ua/ajax.

        Note: ajaxUrl in the meta tag may be a relative path ("/ua/ajax");
        ``_resolve_ajax_url()`` converts it to an absolute URL.
        """
        if self._ajax_url:
            return self._ajax_url

        if self._session is None:
            raise DtekConnectionError(
                "Session not open. Use 'async with DtekClient()' or call connect()."
            )

        # Build the list of paths to try (primary first, then fallbacks without repeats).
        paths_to_try = [self._schedule_path] + [
            p for p in SCHEDULE_PAGE_FALLBACK_PATHS if p != self._schedule_path
        ]

        for path in paths_to_try:
            _LOGGER.debug("Trying schedule path: %s%s", self._base_url, path)
            html = await self._fetch_page_html(path)
            if html is None:
                continue

            # Try all known regex patterns on the page HTML.
            for pattern in _AJAX_PATTERNS:
                match = pattern.search(html)
                if match:
                    raw_url = match.group(1)
                    ajax_url = _resolve_ajax_url(raw_url, self._base_url)
                    _LOGGER.info(
                        "Discovered ajaxUrl: %s (raw=%r, page=%s%s)",
                        ajax_url, raw_url, self._base_url, path,
                    )
                    self._ajax_url = ajax_url
                    self._schedule_path = path  # Cache the working path.
                    return ajax_url

            _LOGGER.debug("No ajaxUrl pattern matched on %s%s.", self._base_url, path)

        # All discovery paths failed — use the hardcoded fallback.
        fallback = f"{self._base_url}{FALLBACK_AJAX_PATH}"
        _LOGGER.warning(
            "Could not discover ajaxUrl from %s (tried %d paths). "
            "Falling back to: %s. "
            "If this fails, open the schedule page in a browser, locate "
            'meta[name="ajaxUrl"] and pass it as ajax_url= to DtekClient().',
            self._base_url,
            len(paths_to_try),
            fallback,
        )
        self._ajax_url = fallback
        return fallback

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _post(self, data: dict[str, Any]) -> Any:
        """Send a form-encoded POST to the AJAX endpoint with retry logic."""
        if self._session is None:
            raise DtekConnectionError(
                "Session not open. Use 'async with DtekClient()' or call connect()."
            )

        ajax_url = await self._get_ajax_url()
        last_error: Exception | None = None

        # Manually encode the payload to ensure correct PHP-style form format.
        encoded_payload = urllib.parse.urlencode(data)

        # Force the headers the PHP server expects (impersonate may override them).
        request_headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        for attempt in range(1, self._retry_attempts + 1):
            try:
                _LOGGER.debug(
                    "POST %s method=%s (attempt %d/%d)",
                    ajax_url,
                    data.get("method"),
                    attempt,
                    self._retry_attempts,
                )
                resp = await self._session.post(
                    ajax_url,
                    data=encoded_payload,
                    headers=request_headers,
                )
                return self._handle_response(resp, ajax_url)

            except DtekServerError as exc:
                last_error = exc
                if attempt < self._retry_attempts:
                    await asyncio.sleep(self._retry_delay * attempt)

            except (DtekUnauthorizedError, DtekNotFoundError, DtekRateLimitError):
                raise

        assert last_error is not None  # noqa: S101
        raise last_error

    def _handle_response(self, response: Any, url: str) -> Any:
        """Translate HTTP errors into typed exceptions, then decode JSON."""
        status: int = response.status_code
        if status == HTTP_UNAUTHORIZED:
            raise DtekUnauthorizedError()
        if status == HTTP_NOT_FOUND:
            raise DtekNotFoundError(url)
        if status == HTTP_TOO_MANY_REQUESTS:
            retry_after: float | None = None
            raw_hdr = response.headers.get("Retry-After")
            if raw_hdr:
                try:
                    retry_after = float(raw_hdr)
                except ValueError:
                    pass
            raise DtekRateLimitError(retry_after)
        if status >= HTTP_SERVER_ERROR:
            raise DtekServerError(status)
        if status >= 400:
            raise DtekAPIError(f"HTTP {status}", status_code=status)

        try:
            payload = response.json()
        except Exception as exc:
            raise DtekDataError(f"Failed to decode JSON from {url}: {exc}") from exc

        if isinstance(payload, dict) and payload.get("result") is False:
            raise DtekDataError("DTEK AJAX returned result=false.", raw=payload)

        return payload

    # ── Form-data builders ────────────────────────────────────────────────────

    @staticmethod
    def _build_form(
        method: str,
        fields: list[tuple[str, str]],
        update_fact: str | None = None,
    ) -> dict[str, Any]:
        """Build the form dict expected by the DTEK AJAX handler.

        The site uses jQuery's serializeArray() format::

            method=getHomeNum
            data[0][name]=city      data[0][value]=м. Українка
            data[1][name]=street    data[1][value]=вул. Юності
            data[2][name]=updateFact   data[2][value]=21.03.2026 16:25
        """
        form: dict[str, Any] = {"method": method}
        for idx, (name, value) in enumerate(fields):
            form[f"data[{idx}][name]"] = name
            form[f"data[{idx}][value]"] = value
        if update_fact is not None:
            idx = len(fields)
            form[f"data[{idx}][name]"] = "updateFact"
            form[f"data[{idx}][value]"] = update_fact
        return form

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_streets(
        self,
        city: str,
        *,
        update_fact: str | None = None,
    ) -> list[StreetSuggestion]:
        """Return all streets available in ``city`` on this DTEK site.

        Per discon-schedule.js (getStreetsInvisibly): getStreets sends only
        ``method=getStreets`` with NO data array. The server returns the full
        city→streets map for the whole region; we filter by city client-side.

        Args:
            city: city name as it appears on the site (e.g. "м. Українка").
            update_fact: timestamp from a previous response (improves server caching).

        Returns:
            A list of :class:`StreetSuggestion` objects, one per street.
        """
        form: dict[str, Any] = {"method": METHOD_GET_STREETS}
        raw = await self._post(form)

        if not isinstance(raw, dict):
            raise DtekDataError("getStreets: expected dict response.", raw=raw)

        # Response key is "streets" (answer.streets in JS), not "data".
        # streets_raw is {"м. Українка": ["вул. Юності", ...], "м. Обухів": [...], ...}
        streets_raw = raw.get("streets", raw.get("data", {}))

        if isinstance(streets_raw, dict):
            city_streets: list[str] | None = streets_raw.get(city)
            if city_streets is None:
                # Case-insensitive fallback.
                city_lower = city.lower()
                for k, v in streets_raw.items():
                    if isinstance(k, str) and k.lower() == city_lower:
                        city_streets = v
                        break
            if city_streets is None:
                _LOGGER.warning(
                    "getStreets: city %r not found in response. "
                    "Available cities: %s",
                    city,
                    sorted(str(k) for k in streets_raw.keys()),
                )
                return []
            if isinstance(city_streets, list):
                return [StreetSuggestion(name=str(s)) for s in city_streets if s]
            return []

        if isinstance(streets_raw, list):
            return [StreetSuggestion(name=str(s)) for s in streets_raw]

        _LOGGER.warning("getStreets: unexpected data structure: %r", type(streets_raw))
        return []

    async def get_home_num(
        self,
        city: str,
        street: str,
        *,
        update_fact: str | None = None,
    ) -> HomeNumResponse:
        """Return all house numbers + group assignments for a city/street.

        This is the core method — it returns the full ``HomeNumResponse`` which
        contains the house→group mapping **plus** the preset and fact schedules.

        Args:
            city: city name (e.g. "м. Українка").
            street: street name (e.g. "вул. Юності").
            update_fact: timestamp from a previous response (enables delta updates).

        Returns:
            :class:`HomeNumResponse` with all house entries and schedule data.
        """
        form = self._build_form(
            METHOD_GET_HOME_NUM,
            [("city", city), ("street", street)],
            update_fact=update_fact,
        )
        raw = await self._post(form)

        if not isinstance(raw, dict):
            raise DtekDataError("getHomeNum: expected dict response.", raw=raw)

        # If the server did not include a schedule, fetch it from the global cache.
        if "preset" not in raw and "fact" not in raw:
            if self._global_schedule is None:
                try:
                    _LOGGER.debug("Fetching global schedule via checkDisconUpdate...")
                    global_raw = await self._post({
                        "method": "checkDisconUpdate",
                        "update": "01.01.2000 00:00",
                    })
                    self._global_schedule = (
                        global_raw if isinstance(global_raw, dict) else {}
                    )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning("Failed to fetch global schedule: %s", exc)
                    self._global_schedule = {}

            if self._global_schedule:
                if "preset" in self._global_schedule:
                    raw["preset"] = self._global_schedule["preset"]
                if "fact" in self._global_schedule:
                    raw["fact"] = self._global_schedule["fact"]

        try:
            return HomeNumResponse.model_validate(raw)
        except ValidationError as exc:
            raise DtekDataError(
                f"getHomeNum: response validation failed: {exc}", raw=raw
            ) from exc

    async def get_group_by_address(
        self,
        city: str,
        street: str,
        house_number: str,
        *,
        update_fact: str | None = None,
    ) -> AddressResult:
        """Find the disconnection group for a specific address.

        Args:
            city: city name (e.g. "м. Українка").
            street: street name (e.g. "вул. Юності").
            house_number: building number (e.g. "10", "10А", "10/2").
            update_fact: optional timestamp from a previous response.

        Returns:
            :class:`AddressResult` with the group_id and display name.

        Raises:
            :exc:`DtekNotFoundError`: if the house number is not in the response.
        """
        response = await self.get_home_num(city, street, update_fact=update_fact)

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
        *,
        update_fact: str | None = None,
    ) -> dict[str, Any] | None:
        """Shortcut: return today's fact-schedule slot map for one house.

        Each slot represents a 30-minute interval (e.g. "00:00–00:30").
        SlotStatus.FIRST / SECOND indicate outage only in the first or second
        half of the slot (~15 min each).

        Returns:
            dict mapping time-zone keys to :class:`SlotStatus`, or ``None``
            if today's schedule is not yet published.
        """
        response = await self.get_home_num(city, street, update_fact=update_fact)
        entry = response.houses.get(house_number)
        if entry is None or not entry.primary_group:
            return None

        if response.fact is None:
            return None

        return response.fact.get_group_today(entry.primary_group)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def site_key(self) -> str:
        """The site_key this client is configured for (e.g. "kem")."""
        return self._site_key

    @property
    def base_url(self) -> str:
        """Base URL of the DTEK regional site."""
        return self._base_url

    @property
    def ajax_url(self) -> str | None:
        """Cached ajaxUrl (None until the first request is made)."""
        return self._ajax_url
