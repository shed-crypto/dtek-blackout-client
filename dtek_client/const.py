"""Constants for the dtek-blackout-client.

DTEK operates a separate WordPress site for each regional subsidiary.
The AJAX endpoint URL is embedded in each page as:
    <meta name="ajaxUrl" content="...">
Note: the content may be a relative path (e.g. "/ua/ajax") rather than
a full URL — DtekClient._get_ajax_url() handles both cases.

Supported regions (SiteKey):
    kem   – DTEK Kyivenerho        (Kyiv city and Kyiv oblast, large cities)
    krem  – DTEK Kyiv Regional     (Kyiv oblast, smaller towns)
    dnem  – DTEK Dnipro            (Dnipro, Dnipropetrovsk oblast)
    dem   – DTEK Donetsk           (government-controlled part of Donetsk oblast)
    oem   – DTEK Odesa             (Odesa, Odesa oblast)
    zem   – DTEK Zaporizhzhia      (Zaporizhzhia)
"""

from typing import Final

# ── Regional site registry ────────────────────────────────────────────────────
# Tuple: (base_url, schedule_page_path)
# schedule_page_path — page that contains <meta name="ajaxUrl">.
# If the primary path does not work, the client tries SCHEDULE_PAGE_FALLBACK_PATHS.
DTEK_SITES: Final[dict[str, tuple[str, str]]] = {
    "kem":  ("https://www.dtek-kem.com.ua",  "/ua/shutdowns"),
    "krem": ("https://www.dtek-krem.com.ua", "/ua/shutdowns"),
    "dnem": ("https://www.dtek-dnem.com.ua", "/ua/shutdowns"),
    "dem":  ("https://www.dtek-dem.com.ua",  "/ua/shutdowns"),
    "oem":  ("https://www.dtek-oem.com.ua",  "/ua/shutdowns"),
    "zem":  ("https://www.dtek-zem.com.ua",  "/ua/shutdowns"),
}

# Fallback schedule page paths tried when the primary path yields no <meta name="ajaxUrl">.
# The client iterates through these in order.
SCHEDULE_PAGE_FALLBACK_PATHS: Final[list[str]] = [
    "/ua/shutdowns",
    "/ua/butt/disconnection-schedule",
    "/ua/disconnection-schedule",
    "/shutdowns",
]

# Default site used when no site_key is specified.
DEFAULT_SITE_KEY: Final = "kem"

# ── AJAX method names ─────────────────────────────────────────────────────────
METHOD_GET_STREETS: Final = "getStreets"
METHOD_GET_HOME_NUM: Final = "getHomeNum"
METHOD_CHECK_UPDATE: Final = "checkDisconUpdate"

# ── Schedule slot values (returned in preset.data / fact.data) ────────────────
# Each slot represents a 30-minute interval (e.g. "00:00–00:30").
# first/second — outage in the first/second half of the 30-min slot (~15 min).
# mfirst/msecond — *possible* outage in the first/second half.
SLOT_YES: Final = "yes"      # electricity available (no outage)
SLOT_NO: Final = "no"        # definite outage for the whole slot
SLOT_MAYBE: Final = "maybe"  # possible outage for the whole slot
SLOT_FIRST: Final = "first"      # outage in the first half of the slot (~15 min)
SLOT_SECOND: Final = "second"    # outage in the second half of the slot (~15 min)
SLOT_MFIRST: Final = "mfirst"    # possible outage in the first half
SLOT_MSECOND: Final = "msecond"  # possible outage in the second half

# ── Day-of-week mapping (DTEK uses 1=Mon, …, 7=Sun — NOT Python's 0-based) ──
DTEK_WEEKDAY: Final[dict[int, int]] = {
    0: 1,  # Python Monday    → DTEK 1
    1: 2,  # Python Tuesday   → DTEK 2
    2: 3,  # Python Wednesday → DTEK 3
    3: 4,  # Python Thursday  → DTEK 4
    4: 5,  # Python Friday    → DTEK 5
    5: 6,  # Python Saturday  → DTEK 6
    6: 7,  # Python Sunday    → DTEK 7
}

# ── HTTP / network defaults ───────────────────────────────────────────────────
DEFAULT_TIMEOUT: Final = 15
DEFAULT_RETRY_ATTEMPTS: Final = 3
DEFAULT_RETRY_DELAY: Final = 1.0

# HTTP status codes
HTTP_OK: Final = 200
HTTP_UNAUTHORIZED: Final = 401
HTTP_NOT_FOUND: Final = 404
HTTP_TOO_MANY_REQUESTS: Final = 429
HTTP_SERVER_ERROR: Final = 500

# ── HTML meta tag name used to locate the AJAX endpoint ──────────────────────
META_AJAX_URL: Final = "ajaxUrl"

# ── Hardcoded fallback AJAX path ──────────────────────────────────────────────
# Used when meta-tag discovery fails (e.g. blocked by WAF).
# Discovered from real sites: meta[name="ajaxUrl"] content="/ua/ajax".
# Full URL = base_url + FALLBACK_AJAX_PATH.
FALLBACK_AJAX_PATH: Final = "/ua/ajax"

# ── Region display names ──────────────────────────────────────────────────────
# English name is listed first; Ukrainian name follows for local context.
# Use REGION_NAMES for UI labels in integrations (e.g. Home Assistant config flow).
REGION_NAMES: Final[dict[str, str]] = {
    "kem":  "DTEK Kyiv City Networks / ДТЕК Київські електромережі (м. Київ)",
    "krem": "DTEK Kyiv Regional Networks / ДТЕК Київські регіональні (Київська обл.)",
    "dnem": "DTEK Dnipro Networks / ДТЕК Дніпровські електромережі",
    "dem":  "DTEK Donetsk Networks / ДТЕК Донецькі електромережі",
    "oem":  "DTEK Odesa Networks / ДТЕК Одеські електромережі",
    "zem":  "DTEK Zaporizhzhia Networks / ДТЕК Запорізькі електромережі",
}

# English-only region names — useful for logs, API responses, and non-Ukrainian UIs.
REGION_NAMES_EN: Final[dict[str, str]] = {
    "kem":  "DTEK Kyiv City Networks",
    "krem": "DTEK Kyiv Regional Networks",
    "dnem": "DTEK Dnipro Networks",
    "dem":  "DTEK Donetsk Networks",
    "oem":  "DTEK Odesa Networks",
    "zem":  "DTEK Zaporizhzhia Networks",
}

# Ukrainian-only region names — for Ukrainian-language UIs.
REGION_NAMES_UA: Final[dict[str, str]] = {
    "kem":  "ДТЕК Київські електромережі (м. Київ)",
    "krem": "ДТЕК Київські регіональні (Київська обл.)",
    "dnem": "ДТЕК Дніпровські електромережі",
    "dem":  "ДТЕК Донецькі електромережі",
    "oem":  "ДТЕК Одеські електромережі",
    "zem":  "ДТЕК Запорізькі електромережі",
}
