"""Constants for dtek-blackout-client.

DTEK operates a separate Yii2 web application for each regional distribution
system operator (DSO). All sites expose their outage data through POST
requests to ``/ua/ajax`` protected by Yii2 CSRF validation.

Supported regions (site_key):
    kem  - DTEK Kyiv City Networks (Kyiv city)
    krem - DTEK Kyiv Regional Networks (Kyiv oblast)
    dnem - DTEK Dnipro Networks (Dnipropetrovsk oblast)
    dem  - DTEK Donetsk Networks (Donetsk oblast)
    oem  - DTEK Odesa Networks (Odesa oblast)
"""

from typing import Final

# Tuple: (base_url, schedule_page_path)
DTEK_SITES: Final[dict[str, tuple[str, str]]] = {
    "kem": ("https://www.dtek-kem.com.ua", "/ua/shutdowns"),
    "krem": ("https://www.dtek-krem.com.ua", "/ua/shutdowns"),
    "dnem": ("https://www.dtek-dnem.com.ua", "/ua/shutdowns"),
    "dem": ("https://www.dtek-dem.com.ua", "/ua/shutdowns"),
    "oem": ("https://www.dtek-oem.com.ua", "/ua/shutdowns"),
}

SCHEDULE_PAGE_FALLBACK_PATHS: Final[list[str]] = [
    "/ua/shutdowns",
    "/ua/butt/disconnection-schedule",
    "/ua/disconnection-schedule",
    "/shutdowns",
]

DEFAULT_SITE_KEY: Final = "kem"
DEFAULT_TIMEZONE: Final = "Europe/Kyiv"

# AJAX method names
METHOD_GET_STREETS: Final = "getStreets"
METHOD_GET_HOME_NUM: Final = "getHomeNum"
METHOD_CHECK_UPDATE: Final = "checkDisconUpdate"

# Passing any truthy updateFact string that differs from the current server
# timestamp instructs the Yii2 handler to include fact and preset schedules
# directly in the getHomeNum response.
FORCE_UPDATE_FACT: Final = "01.01.2000 00:00"

# Prefix of the signed Yii2 CSRF cookie issued by DTEK regional sites.
CSRF_COOKIE_PREFIX: Final = "_csrf-dtek-"

# Schedule slot values (30-minute intervals in preset.data / fact.data).
SLOT_YES: Final = "yes"
SLOT_NO: Final = "no"
SLOT_MAYBE: Final = "maybe"
SLOT_FIRST: Final = "first"
SLOT_SECOND: Final = "second"
SLOT_MFIRST: Final = "mfirst"
SLOT_MSECOND: Final = "msecond"

# DTEK uses 1-based ISO weekday indices (1=Mon ... 7=Sun).
DTEK_WEEKDAY: Final[dict[int, int]] = {
    0: 1,
    1: 2,
    2: 3,
    3: 4,
    4: 5,
    5: 6,
    6: 7,
}

DEFAULT_TIMEOUT: Final = 15
DEFAULT_RETRY_ATTEMPTS: Final = 3
DEFAULT_RETRY_DELAY: Final = 1.0

HTTP_OK: Final = 200
HTTP_BAD_REQUEST: Final = 400
HTTP_UNAUTHORIZED: Final = 401
HTTP_NOT_FOUND: Final = 404
HTTP_TOO_MANY_REQUESTS: Final = 429
HTTP_SERVER_ERROR: Final = 500

META_AJAX_URL: Final = "ajaxUrl"
FALLBACK_AJAX_PATH: Final = "/ua/ajax"

REGION_NAMES: Final[dict[str, str]] = {
    "kem": "DTEK Kyiv City Networks / ДТЕК Київські електромережі (м. Київ)",
    "krem": "DTEK Kyiv Regional Networks / ДТЕК Київські регіональні (Київська обл.)",
    "dnem": "DTEK Dnipro Networks / ДТЕК Дніпровські електромережі",
    "dem": "DTEK Donetsk Networks / ДТЕК Донецькі електромережі",
    "oem": "DTEK Odesa Networks / ДТЕК Одеські електромережі",
}

REGION_NAMES_EN: Final[dict[str, str]] = {
    "kem": "DTEK Kyiv City Networks",
    "krem": "DTEK Kyiv Regional Networks",
    "dnem": "DTEK Dnipro Networks",
    "dem": "DTEK Donetsk Networks",
    "oem": "DTEK Odesa Networks",
}

REGION_NAMES_UA: Final[dict[str, str]] = {
    "kem": "ДТЕК Київські електромережі (м. Київ)",
    "krem": "ДТЕК Київські регіональні (Київська обл.)",
    "dnem": "ДТЕК Дніпровські електромережі",
    "dem": "ДТЕК Донецькі електромережі",
    "oem": "ДТЕК Одеські електромережі",
}
