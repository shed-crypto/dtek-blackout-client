"""Async HTTP client for DTEK regional disconnection-schedule sites.

Architecture
------------
DTEK regional sites (e.g. dtek-kem.com.ua, dtek-krem.com.ua) are Yii2 web
applications. While HTML pages such as ``/ua/shutdowns`` are gated by an
Imperva Incapsula JavaScript challenge, the AJAX endpoint ``POST /ua/ajax``
is not challenged and is protected by Yii2 CSRF validation:

1. A POST request without a token returns HTTP 400 and sets a signed
   ``_csrf-dtek-<site>`` cookie containing the serialized 32-byte raw token.
2. Subsequent POST requests succeed when ``X-CSRF-Token`` carries the masked
   token: ``base64url(mask + (mask XOR token))``.

This client uses ``aiohttp.ClientSession`` so it works standalone and inside
Home Assistant without requiring a headless browser or native CFFI libraries.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import re
import secrets
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import aiohttp
from pydantic import ValidationError

from .const import (
    CSRF_COOKIE_PREFIX,
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_RETRY_DELAY,
    DEFAULT_SITE_KEY,
    DEFAULT_TIMEOUT,
    DEFAULT_TIMEZONE,
    DTEK_SITES,
    FALLBACK_AJAX_PATH,
    FORCE_UPDATE_FACT,
    HTTP_BAD_REQUEST,
    HTTP_NOT_FOUND,
    HTTP_SERVER_ERROR,
    HTTP_TOO_MANY_REQUESTS,
    HTTP_UNAUTHORIZED,
    META_AJAX_URL,
    METHOD_CHECK_UPDATE,
    METHOD_GET_HOME_NUM,
    METHOD_GET_STREETS,
    SCHEDULE_PAGE_FALLBACK_PATHS,
)
from .exceptions import (
    DtekAPIError,
    DtekBlockedError,
    DtekConnectionError,
    DtekDataError,
    DtekNotFoundError,
    DtekRateLimitError,
    DtekServerError,
    DtekSiteError,
    DtekSSLError,
    DtekTimeoutError,
    DtekUnauthorizedError,
)
from .models import AddressResult, HomeNumResponse, SlotStatus, StreetSuggestion

__all__ = ["DtekClient", "extract_csrf_token", "mask_csrf_token"]
_LOGGER = logging.getLogger(__name__)

_META_RE = re.compile(
    r'<meta\s[^>]*name=["\']' + META_AJAX_URL + r'["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_META_RE2 = re.compile(
    r'<meta\s[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']' + META_AJAX_URL + r'["\']',
    re.IGNORECASE,
)
_JS_VAR_RE = re.compile(
    r'var\s+ajaxUrl\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_JS_OBJ_RE = re.compile(
    r'["\']ajaxUrl["\']\s*:\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_WP_AJAX_RE = re.compile(
    r'["\']ajax_url["\']\s*:\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

_AJAX_PATTERNS = [_META_RE, _META_RE2, _JS_VAR_RE, _JS_OBJ_RE, _WP_AJAX_RE]
_INCAPSULA_MARKERS = ("_Incapsula_Resource", "visid_incap", "incap_ses")
_CHALLENGE_MARKER = "_Incapsula_Resource"
_CSRF_TOKEN_RE = re.compile(r'i:1;s:\d+:"([^"]+)"')

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def extract_csrf_token(cookie_value: str) -> str | None:
    """Extract the raw token from a Yii2 serialized CSRF cookie value."""
    match = _CSRF_TOKEN_RE.search(unquote(cookie_value))
    return match.group(1) if match else None


def mask_csrf_token(token: str, mask: bytes | None = None) -> str:
    """Mask a raw token using the Yii2 Security::maskToken algorithm."""
    raw = token.encode("utf-8")
    if mask is None:
        mask = secrets.token_bytes(len(raw))
    masked = bytes(a ^ b for a, b in zip(mask, raw, strict=True))
    return base64.urlsafe_b64encode(mask + masked).decode("ascii")


def _resolve_ajax_url(raw: str, base_url: str) -> str:
    """Resolve an ajaxUrl that may be a relative path against base_url."""
    cleaned = raw.replace("\\/", "/").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme:
        return cleaned
    return urljoin(base_url, cleaned)


class DtekClient:
    """Asynchronous client for DTEK regional disconnection-schedule sites.

    Args:
        site_key: Regional key defined in ``DTEK_SITES`` (e.g. ``"kem"``, ``"krem"``).
        ajax_url: Explicit AJAX endpoint URL. When omitted, ``base_url + /ua/ajax``
                  is used unless ``discover_ajax_url=True`` is specified.
        timeout: Per-request timeout in seconds.
        retry_attempts: Number of attempts on transient 5xx responses.
        retry_delay: Base delay in seconds between retries (linear back-off).
        session: Existing ``aiohttp.ClientSession`` (for example, created via
                 Home Assistant's ``async_create_clientsession``).
        session_factory: Zero-argument callable that creates a new
                         ``aiohttp.ClientSession`` if the current session is closed.
        user_agent: Custom ``User-Agent`` header sent with requests.
        csrf_token: Pre-configured CSRF token (raw or masked). When omitted,
                    the client automatically bootstraps a token from ``/ua/ajax``.
        discover_ajax_url: When True and ``ajax_url`` is None, fetch the HTML
                           schedule page to discover ``<meta name="ajaxUrl">``.
    """

    def __init__(
        self,
        site_key: str = DEFAULT_SITE_KEY,
        *,
        ajax_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        session: aiohttp.ClientSession | None = None,
        session_factory: Callable[[], aiohttp.ClientSession] | None = None,
        user_agent: str | None = None,
        csrf_token: str | None = None,
        discover_ajax_url: bool = False,
    ) -> None:
        if site_key not in DTEK_SITES:
            raise DtekSiteError(
                f"Unknown site_key {site_key!r}. Valid options: {sorted(DTEK_SITES.keys())}"
            )

        self._site_key = site_key
        self._base_url, self._schedule_path = DTEK_SITES[site_key]
        self._ajax_url: str | None = ajax_url
        self._discover_ajax_url = discover_ajax_url
        self._timeout = timeout
        self._retry_attempts = max(1, retry_attempts)
        self._retry_delay = retry_delay
        self._session: aiohttp.ClientSession | None = session
        self._session_factory = session_factory
        self._owns_session: bool = session is None and session_factory is None
        self._user_agent = user_agent or DEFAULT_USER_AGENT
        self._csrf_token: str | None = csrf_token
        self._csrf_is_raw: bool = False
        self._csrf_lock = asyncio.Lock()
        self._global_schedule: dict[str, Any] | None = None
        self._streets_cache: dict[str, Any] | None = None

    def _get_active_session(self) -> aiohttp.ClientSession:
        """Return an open session, recreating it via session_factory if closed."""
        if self._session is not None and getattr(self._session, "closed", False):
            if self._session_factory is not None:
                self._session = self._session_factory()
                self._csrf_token = None
                self._csrf_is_raw = False
            else:
                raise DtekConnectionError("Injected aiohttp.ClientSession is closed.")

        if self._session is None and self._session_factory is not None:
            self._session = self._session_factory()
            self._csrf_token = None
            self._csrf_is_raw = False

        if self._session is None:
            raise DtekConnectionError(
                "Session not open. Use 'async with DtekClient()' or call connect()."
            )

        return self._session

    async def connect(self) -> None:
        """Open an internal aiohttp.ClientSession when no session was injected."""
        if self._session is None:
            if self._session_factory is not None:
                self._session = self._session_factory()
            else:
                self._session = aiohttp.ClientSession(
                    cookie_jar=aiohttp.CookieJar(),
                    timeout=aiohttp.ClientTimeout(total=self._timeout),
                )
                self._owns_session = True

    async def close(self) -> None:
        """Close the session if this client created and owns it."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> DtekClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def _fetch_page_html(self, path: str) -> str | None:
        """Fetch a schedule page and return its HTML, or None on 404 or WAF challenge."""
        session = self._get_active_session()
        url = f"{self._base_url}{path}"
        try:
            async with session.get(
                url,
                headers={"User-Agent": self._user_agent},
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                status = resp.status
                text = await resp.text()
        except TimeoutError as exc:
            raise DtekTimeoutError(self._timeout) from exc
        except (aiohttp.ClientSSLError, aiohttp.ClientConnectorSSLError) as exc:
            raise DtekSSLError(f"SSL error connecting to {url}: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise DtekConnectionError(f"Cannot reach {url}: {exc}") from exc

        if status == HTTP_NOT_FOUND:
            return None
        if status >= HTTP_SERVER_ERROR:
            raise DtekServerError(status)

        if any(marker in text for marker in _INCAPSULA_MARKERS):
            _LOGGER.warning("WAF challenge detected on %s; skipping HTML discovery.", url)
            return None

        return text

    async def _get_ajax_url(self) -> str:
        """Return the AJAX endpoint URL, discovering it from HTML if requested."""
        if self._ajax_url:
            return self._ajax_url

        self._get_active_session()

        if self._discover_ajax_url:
            paths_to_try = [self._schedule_path] + [
                p for p in SCHEDULE_PAGE_FALLBACK_PATHS if p != self._schedule_path
            ]

            for path in paths_to_try:
                html = await self._fetch_page_html(path)
                if html is None:
                    continue

                for pattern in _AJAX_PATTERNS:
                    match = pattern.search(html)
                    if match:
                        raw_url = match.group(1)
                        ajax_url = _resolve_ajax_url(raw_url, self._base_url)
                        self._ajax_url = ajax_url
                        self._schedule_path = path
                        return ajax_url

        fallback = f"{self._base_url}{FALLBACK_AJAX_PATH}"
        self._ajax_url = fallback
        return fallback

    def _extract_token_from_cookies(self, cookies: Any) -> bool:
        """Inspect a cookie mapping for a Yii2 CSRF cookie and store the raw token."""
        if not cookies:
            return False
        items = cookies.items() if isinstance(cookies, Mapping) else []
        for name, morsel in items:
            cookie_name = str(name)
            if cookie_name.startswith(CSRF_COOKIE_PREFIX) or cookie_name.startswith("_csrf"):
                raw_val = getattr(morsel, "value", morsel)
                if isinstance(raw_val, str):
                    extracted = extract_csrf_token(raw_val)
                    if extracted:
                        self._csrf_token = extracted
                        self._csrf_is_raw = True
                        return True
        return False

    def _extract_token_from_jar(self, session: aiohttp.ClientSession) -> bool:
        """Inspect the session cookie jar for an existing Yii2 CSRF cookie."""
        cookie_jar = getattr(session, "cookie_jar", None)
        if cookie_jar is None:
            return False
        try:
            for cookie in cookie_jar:
                name = getattr(cookie, "key", "")
                value = getattr(cookie, "value", "")
                if (
                    isinstance(name, str)
                    and (name.startswith(CSRF_COOKIE_PREFIX) or name.startswith("_csrf"))
                    and isinstance(value, str)
                ):
                    extracted = extract_csrf_token(value)
                    if extracted:
                        self._csrf_token = extracted
                        self._csrf_is_raw = True
                        return True
        except TypeError:
            return False
        return False

    def _build_headers(self, token: str | None, *, is_raw_token: bool) -> dict[str, str]:
        """Build HTTP headers for an AJAX POST request."""
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "uk,en-US;q=0.9,en;q=0.8",
            "Origin": self._base_url,
            "Referer": f"{self._base_url}{self._schedule_path}",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        if token is not None:
            headers["X-CSRF-Token"] = mask_csrf_token(token) if is_raw_token else token
        return headers

    async def _send_raw_post(
        self,
        ajax_url: str,
        form: Mapping[str, Any],
        token: str | None,
        *,
        is_raw_token: bool,
    ) -> tuple[int, str, Mapping[str, Any]]:
        """Execute a single POST request and return (status, body_text, headers)."""
        session = self._get_active_session()
        headers = self._build_headers(token, is_raw_token=is_raw_token)
        try:
            async with session.post(
                ajax_url,
                data=dict(form),
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                self._extract_token_from_cookies(getattr(resp, "cookies", None))
                status = int(resp.status)
                text = await resp.text()
                resp_headers: Mapping[str, Any] = getattr(resp, "headers", {}) or {}
                return status, text, resp_headers
        except TimeoutError as exc:
            raise DtekTimeoutError(self._timeout) from exc
        except (aiohttp.ClientSSLError, aiohttp.ClientConnectorSSLError) as exc:
            raise DtekSSLError(f"SSL error posting to {ajax_url}: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise DtekConnectionError(f"Error requesting {ajax_url}: {exc}") from exc

    async def _ensure_csrf_token(
        self,
        ajax_url: str,
        *,
        stale: str | None = None,
    ) -> tuple[str | None, bool]:
        """Return (csrf_token, is_raw), bootstrapping from /ua/ajax if needed."""
        async with self._csrf_lock:
            session = self._get_active_session()
            if stale is not None and self._csrf_token == stale:
                self._csrf_token = None
                self._csrf_is_raw = False
                cookie_jar = getattr(session, "cookie_jar", None)
                if cookie_jar is not None and hasattr(cookie_jar, "clear"):
                    try:
                        cookie_jar.clear(lambda c: str(getattr(c, "key", "")).startswith("_csrf"))
                    except TypeError:
                        pass

            if self._csrf_token is None:
                self._extract_token_from_jar(session)

            if self._csrf_token is None:
                # A POST without X-CSRF-Token returns HTTP 400 and sets _csrf-dtek-<site>.
                await self._send_raw_post(
                    ajax_url,
                    {"method": METHOD_GET_HOME_NUM},
                    None,
                    is_raw_token=False,
                )
                if self._csrf_token is None:
                    self._extract_token_from_jar(session)

            return self._csrf_token, self._csrf_is_raw

    async def _post(self, data: dict[str, Any]) -> Any:
        """Send a form-encoded POST to the AJAX endpoint with CSRF and 5xx retry logic."""
        self._get_active_session()
        ajax_url = await self._get_ajax_url()
        last_error: Exception | None = None

        for attempt in range(1, self._retry_attempts + 1):
            try:
                token, is_raw = await self._ensure_csrf_token(ajax_url)
                status, text, resp_headers = await self._send_raw_post(
                    ajax_url,
                    data,
                    token,
                    is_raw_token=is_raw,
                )

                if status == HTTP_BAD_REQUEST:
                    # Refresh stale or rejected CSRF token once and retry immediately.
                    if self._csrf_token == token:
                        token, is_raw = await self._ensure_csrf_token(
                            ajax_url,
                            stale=token or "",
                        )
                    else:
                        token, is_raw = self._csrf_token, self._csrf_is_raw

                    if token is not None:
                        status, text, resp_headers = await self._send_raw_post(
                            ajax_url,
                            data,
                            token,
                            is_raw_token=is_raw,
                        )

                return self._handle_response(status, text, resp_headers, ajax_url)

            except DtekServerError as exc:
                last_error = exc
                if attempt < self._retry_attempts:
                    await asyncio.sleep(self._retry_delay * attempt)

            except (
                DtekUnauthorizedError,
                DtekNotFoundError,
                DtekRateLimitError,
                DtekBlockedError,
            ):
                raise

        assert last_error is not None
        raise last_error

    def _handle_response(
        self,
        status: int,
        text: str,
        headers: Mapping[str, Any],
        url: str,
    ) -> Any:
        """Translate HTTP status codes and WAF markers into exceptions, then decode JSON."""
        if _CHALLENGE_MARKER in text:
            raise DtekBlockedError(f"DTEK returned an anti-bot challenge for {url}")
        if status == HTTP_UNAUTHORIZED:
            raise DtekUnauthorizedError()
        if status == HTTP_NOT_FOUND:
            raise DtekNotFoundError(url)
        if status == HTTP_TOO_MANY_REQUESTS:
            retry_after: float | None = None
            raw_hdr = headers.get("Retry-After")
            if raw_hdr:
                try:
                    retry_after = float(raw_hdr)
                except ValueError:
                    pass
            raise DtekRateLimitError(retry_after)
        if status >= HTTP_SERVER_ERROR:
            raise DtekServerError(status)
        if status >= HTTP_BAD_REQUEST:
            raise DtekAPIError(f"HTTP {status}", status_code=status)

        try:
            payload = json.loads(text)
        except Exception as exc:
            raise DtekDataError(f"Failed to decode JSON from {url}: {exc}") from exc

        if isinstance(payload, dict) and payload.get("result") is False:
            raise DtekDataError("DTEK AJAX returned result=false.", raw=payload)

        return payload

    @staticmethod
    def _build_form(
        method: str,
        fields: list[tuple[str, str]],
        update_fact: str | None = None,
    ) -> dict[str, Any]:
        """Build the jQuery serializeArray form dict expected by the DTEK AJAX handler."""
        form: dict[str, Any] = {"method": method}
        for idx, (name, value) in enumerate(fields):
            form[f"data[{idx}][name]"] = name
            form[f"data[{idx}][value]"] = value
        if update_fact is not None:
            idx = len(fields)
            form[f"data[{idx}][name]"] = "updateFact"
            form[f"data[{idx}][value]"] = update_fact
        return form

    async def _fetch_streets_raw(self, *, refresh: bool = False) -> dict[str, Any]:
        """Fetch and cache the raw getStreets payload on this client instance."""
        if refresh or self._streets_cache is None:
            raw = await self._post({"method": METHOD_GET_STREETS})
            if not isinstance(raw, dict):
                raise DtekDataError("getStreets: expected dict response.", raw=raw)
            self._streets_cache = raw
        return self._streets_cache

    async def get_all_streets(self, *, refresh: bool = False) -> dict[str, list[str]]:
        """Return the complete settlement-to-streets dictionary for this DTEK site.

        On ``kem`` (Kyiv city), the server returns a flat list of streets; this
        method normalizes it under the ``"м. Київ"`` settlement key. The regional
        street directory (~470 KB) is cached on the client instance unless
        ``refresh=True`` is passed.
        """
        raw = await self._fetch_streets_raw(refresh=refresh)

        streets_raw = raw.get("streets", raw.get("data", {}))
        if isinstance(streets_raw, list):
            return {"м. Київ": [str(s) for s in streets_raw if s]}

        if isinstance(streets_raw, dict):
            result: dict[str, list[str]] = {}
            for settlement, names in streets_raw.items():
                if isinstance(settlement, str) and isinstance(names, list):
                    result[settlement] = [str(s) for s in names if s]
            return result

        return {}

    async def get_streets(
        self,
        city: str | None = None,
        *,
        refresh: bool = False,
    ) -> list[StreetSuggestion]:
        """Return streets available in ``city`` on this DTEK site.

        Args:
            city: Settlement name as it appears on the site (e.g. ``"м. Українка"``).
                  Optional on ``kem`` (Kyiv city) where the site returns a flat list.
            refresh: Bypass the instance street cache and fetch fresh data.
        """
        raw = await self._fetch_streets_raw(refresh=refresh)
        streets_raw = raw.get("streets", raw.get("data", {}))

        if isinstance(streets_raw, list):
            return [StreetSuggestion(name=str(s)) for s in streets_raw if s]

        if isinstance(streets_raw, dict):
            if city is None:
                unique_streets = sorted(
                    {
                        str(s)
                        for names in streets_raw.values()
                        if isinstance(names, list)
                        for s in names
                        if s
                    }
                )
                return [StreetSuggestion(name=s) for s in unique_streets]

            city_streets: Any = streets_raw.get(city)
            if city_streets is None:
                city_lower = city.lower()
                for k, v in streets_raw.items():
                    if isinstance(k, str) and k.lower() == city_lower:
                        city_streets = v
                        break
            if city_streets is None:
                _LOGGER.warning(
                    "getStreets: city %r not found in response. Available cities: %d",
                    city,
                    len(streets_raw),
                )
                return []
            if isinstance(city_streets, list):
                return [StreetSuggestion(name=str(s)) for s in city_streets if s]
            return []

        _LOGGER.warning("getStreets: unexpected data structure: %r", type(streets_raw))
        return []

    async def get_home_num(
        self,
        city: str,
        street: str,
        *,
        update_fact: str | None = None,
    ) -> HomeNumResponse:
        """Return all house numbers, group assignments, and schedules for a street.

        Args:
            city: Settlement name (e.g. ``"м. Українка"``).
            street: Street name (e.g. ``"вул. Юності"``).
            update_fact: Optional version timestamp from a previous response.
                         Defaults to ``FORCE_UPDATE_FACT`` so the server includes
                         both ``fact`` and ``preset`` schedules in a single response.
        """
        effective_update_fact = update_fact if update_fact is not None else FORCE_UPDATE_FACT
        form = self._build_form(
            METHOD_GET_HOME_NUM,
            [("city", city), ("street", street)],
            update_fact=effective_update_fact,
        )
        raw = await self._post(form)

        if not isinstance(raw, dict):
            raise DtekDataError("getHomeNum: expected dict response.", raw=raw)

        if "preset" in raw or "fact" in raw:
            # Keep the cached global schedule synchronized whenever fresh schedule
            # blocks arrive so subsequent delta responses never fall back to stale data.
            updated_cache = dict(self._global_schedule) if self._global_schedule else {}
            if "preset" in raw:
                updated_cache["preset"] = raw["preset"]
            if "fact" in raw:
                updated_cache["fact"] = raw["fact"]
            self._global_schedule = updated_cache
        else:
            if self._global_schedule is None:
                try:
                    global_raw = await self._post(
                        {
                            "method": METHOD_CHECK_UPDATE,
                            "update": FORCE_UPDATE_FACT,
                        }
                    )
                    self._global_schedule = global_raw if isinstance(global_raw, dict) else {}
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning("Failed to fetch global schedule: %s", exc)
                    self._global_schedule = {}

            if self._global_schedule:
                raw = dict(raw)
                if "preset" in self._global_schedule:
                    raw["preset"] = self._global_schedule["preset"]
                if "fact" in self._global_schedule:
                    raw["fact"] = self._global_schedule["fact"]

        try:
            return HomeNumResponse.model_validate(raw)
        except ValidationError as exc:
            raise DtekDataError(f"getHomeNum: response validation failed: {exc}", raw=raw) from exc

    async def get_group_by_address(
        self,
        city: str,
        street: str,
        house_number: str,
        *,
        update_fact: str | None = None,
        response: HomeNumResponse | None = None,
    ) -> AddressResult:
        """Find the disconnection group for a specific address.

        Args:
            city: Settlement name (e.g. ``"м. Українка"``).
            street: Street name (e.g. ``"вул. Юності"``).
            house_number: Building number (e.g. ``"10"``, ``"10А"``, ``"10/2"``).
            update_fact: Optional timestamp from a previous response.
            response: Pre-fetched ``HomeNumResponse`` to avoid a duplicate request.
        """
        resolved = response or await self.get_home_num(city, street, update_fact=update_fact)
        entry = resolved.find_house(house_number)
        if entry is None:
            raise DtekNotFoundError(
                f"House {house_number!r} not found on {street!r}, {city!r}. "
                f"Available numbers: {', '.join(sorted(resolved.houses.keys()))}"
            )

        group_id = entry.primary_group or "unknown"
        group_name = ""
        if resolved.preset and group_id in resolved.preset.sch_names:
            group_name = resolved.preset.sch_names[group_id]

        return AddressResult(
            site_key=self._site_key,
            city=city,
            street=street,
            house_number=entry.house_number,
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
        response: HomeNumResponse | None = None,
    ) -> dict[str, SlotStatus] | None:
        """Return today's confirmed schedule slot map for one house, or None."""
        resolved = response or await self.get_home_num(city, street, update_fact=update_fact)
        entry = resolved.find_house(house_number)
        if entry is None or not entry.primary_group or resolved.fact is None:
            return None

        return resolved.fact.get_group_today(entry.primary_group)

    async def get_tomorrow_schedule(
        self,
        city: str,
        street: str,
        house_number: str,
        *,
        update_fact: str | None = None,
        response: HomeNumResponse | None = None,
    ) -> dict[str, SlotStatus] | None:
        """Return tomorrow's confirmed schedule slot map for one house, or None."""
        resolved = response or await self.get_home_num(city, street, update_fact=update_fact)
        entry = resolved.find_house(house_number)
        if entry is None or not entry.primary_group or resolved.fact is None:
            return None

        tomorrow_date = resolved.fact.today_date + datetime.timedelta(days=1)
        return resolved.fact.get_group_for_date(tomorrow_date, entry.primary_group)

    async def get_schedule_for_date(
        self,
        city: str,
        street: str,
        house_number: str,
        date: datetime.date,
        *,
        update_fact: str | None = None,
        response: HomeNumResponse | None = None,
    ) -> dict[str, SlotStatus] | None:
        """Return the confirmed schedule slot map for a specific calendar date."""
        resolved = response or await self.get_home_num(city, street, update_fact=update_fact)
        entry = resolved.find_house(house_number)
        if entry is None or not entry.primary_group or resolved.fact is None:
            return None

        return resolved.fact.get_group_for_date(date, entry.primary_group)

    @staticmethod
    def get_available_fact_dates(response: Any) -> list[datetime.date]:
        """Return all calendar dates available in a ``HomeNumResponse.fact``."""
        if response.fact is None:
            return []
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        dates: list[datetime.date] = []
        for ts_str in response.fact.days:
            try:
                ts = int(ts_str)
                d = datetime.datetime.fromtimestamp(ts, tz=tz).date()
                dates.append(d)
            except (ValueError, OSError):
                continue
        return sorted(dates)

    @property
    def site_key(self) -> str:
        """The regional site_key this client is configured for."""
        return self._site_key

    @property
    def base_url(self) -> str:
        """Base URL of the DTEK regional site."""
        return self._base_url

    @property
    def ajax_url(self) -> str | None:
        """Configured or discovered ajaxUrl (None until resolved if not pre-set)."""
        return self._ajax_url
