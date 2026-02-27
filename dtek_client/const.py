"""Constants for the dtek-blackout-client."""

from typing import Final

# ── Regional site registry ────────────────────────────────────────────────────
# Tuple: (base_url, schedule_page_path)
DTEK_SITES: Final[dict[str, tuple[str, str]]] = {
    "kem":  ("https://www.dtek-kem.com.ua",  "/ua/shutdowns"),
    "krem": ("https://www.dtek-krem.com.ua", "/ua/shutdowns"),
}

DEFAULT_SITE_KEY: Final = "kem"

# ── AJAX method names ─────────────────────────────────────────────────────────
METHOD_GET_STREETS: Final = "getStreets"
METHOD_GET_HOME_NUM: Final = "getHomeNum"
METHOD_CHECK_UPDATE: Final = "checkDisconUpdate"

# ── Schedule slot values ──────────────────────────────────────────────────────
SLOT_YES: Final = "yes"      # electricity available (no outage)
SLOT_NO: Final = "no"        # definite outage for the whole slot
SLOT_MAYBE: Final = "maybe"  # possible outage for the whole slot
SLOT_FIRST: Final = "first"      # outage in the first half of the slot (~15 min)
SLOT_SECOND: Final = "second"    # outage in the second half of the slot (~15 min)
SLOT_MFIRST: Final = "mfirst"    # possible outage in the first half
SLOT_MSECOND: Final = "msecond"  # possible outage in the second half

# ── Day-of-week mapping (DTEK uses 1=Mon, …, 7=Sun) ─────────────────────────
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

# HTTP status codes
HTTP_OK: Final = 200
HTTP_UNAUTHORIZED: Final = 401
HTTP_NOT_FOUND: Final = 404
HTTP_SERVER_ERROR: Final = 500

# ── HTML meta tag name used to locate the AJAX endpoint ──────────────────────
META_AJAX_URL: Final = "ajaxUrl"