# dtek-blackout-client

> Async Python client for **DTEK** regional electricity-outage schedule sites

[![CI](https://github.com/shed-crypto/dtek-blackout-client/actions/workflows/ci.yml/badge.svg)](https://github.com/shed-crypto/dtek-blackout-client/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/dtek-blackout-client.svg)](https://pypi.org/project/dtek-blackout-client/)
[![Python versions](https://img.shields.io/pypi/pyversions/dtek-blackout-client.svg)](https://pypi.org/project/dtek-blackout-client/)
[![codecov](https://codecov.io/gh/shed-crypto/dtek-blackout-client/branch/main/graph/badge.svg)](https://codecov.io/gh/shed-crypto/dtek-blackout-client)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is DTEK?

[DTEK](https://dtek.com/) is Ukraine's largest private electricity company.
Its regional distribution system operators (DSOs) maintain websites that publish
planned and confirmed disconnection schedules across Ukraine.

Unlike YASNO, **DTEK sites use a Yii2 AJAX endpoint (`/ua/ajax`)** rather than
a public REST API. This library implements the Yii2 CSRF and AJAX protocol used
by the frontend (`discon-schedule.js`) to provide a clean, typed, universal
`aiohttp` interface that works standalone and inside Home Assistant.

### Supported regions

| `site_key` | English name | Ukrainian name | Coverage |
|---|---|---|---|
| `kem`  | DTEK Kyiv City Networks       | ДТЕК Київські електромережі    | Kyiv city |
| `krem` | DTEK Kyiv Regional Networks   | ДТЕК Київські регіональні      | Kyiv oblast (Ukrainka, Obukhiv, Irpin, Fastiv...) |
| `dnem` | DTEK Dnipro Networks          | ДТЕК Дніпровські електромережі | Dnipro, Dnipropetrovsk oblast |
| `dem`  | DTEK Donetsk Networks         | ДТЕК Донецькі електромережі    | Government-controlled Donetsk oblast |
| `oem`  | DTEK Odesa Networks           | ДТЕК Одеські електромережі     | Odesa, Odesa oblast |

Region names are also available programmatically via `const.REGION_NAMES`,
`REGION_NAMES_EN`, and `REGION_NAMES_UA`.

---

## Features

- **Universal & Home Assistant ready** — built on standard `aiohttp.ClientSession` with support for injected sessions and `session_factory`
- **Automatic Yii2 CSRF bootstrap** — extracts `_csrf-dtek-*` cookies from `/ua/ajax`, masks tokens per Yii2 `Security::maskToken`, and refreshes expired tokens on HTTP 400 without needing a headless browser
- **Typed** — every model uses `pydantic` v2 with strict validation and `frozen=True`
- **DST-safe timezone handling** — resolves schedule dates in `Europe/Kyiv` via `zoneinfo` + `tzdata`, accurately handling 23-hour and 25-hour daylight saving transitions
- **Tolerant house matching** — matches building numbers across Cyrillic/Latin lookalike characters and spacing variations (e.g. `8 a` -> `8а`, Latin to Cyrillic)
- **Resilient** — automatic retry with linear back-off on 5xx errors
- **Stub included** — `StubDtekClient` enables offline development without network access
- **Tested** — 99%+ test coverage with all HTTP calls mocked in CI

---

## Installation

```bash
pip install dtek-blackout-client
```

Or with Poetry:

```bash
poetry add dtek-blackout-client
```

Optional Playwright fallback (only if browser-based HTML cookie harvesting is needed):

```bash
pip install "dtek-blackout-client[browser]"
playwright install chromium
```

---

## Quick start

```python
import asyncio
from dtek_client import DtekClient

async def main() -> None:
    async with DtekClient("krem") as client:
        # 1. Get all streets in a settlement
        streets = await client.get_streets("м. Українка")
        print([s.name for s in streets[:5]])

        # 2. Get all houses, groups, and schedules for a street in a single request
        response = await client.get_home_num("м. Українка", "вул. Юності")
        for house, entry in sorted(response.houses.items()):
            status = "excluded" if entry.is_excluded else entry.primary_group
            print(f"  {house:6s} -> {status}")

        # 3. Reuse the fetched response to look up group and today's schedule
        result = await client.get_group_by_address(
            city="м. Українка",
            street="вул. Юності",
            house_number="1",
            response=response,
        )
        print(result)

        slots = await client.get_today_schedule(
            city="м. Українка",
            street="вул. Юності",
            house_number="1",
            response=response,
        )
        print(slots)

asyncio.run(main())
```

---

## How DTEK sites work (protocol overview)

```text
1. POST https://www.dtek-krem.com.ua/ua/ajax (without X-CSRF-Token)
   -> HTTP 400 + Set-Cookie: _csrf-dtek-krem=<signed Yii2 token>
   -> Client extracts raw 32-byte token and computes masked X-CSRF-Token:
      base64url(mask + (mask XOR token))

2. POST /ua/ajax  (application/x-www-form-urlencoded + X-CSRF-Token)
   method=getStreets
   -> {"result": true, "streets": {"м. Українка": ["вул. Юності", ...]}}
      (on kem, "streets" is a flat list of Kyiv streets)

3. POST /ua/ajax  (with X-CSRF-Token)
   method=getHomeNum
   data[0][name]=city       & data[0][value]=м. Українка
   data[1][name]=street     & data[1][value]=вул. Юності
   data[2][name]=updateFact & data[2][value]=01.01.2000 00:00
   -> {
        "result": true,
        "data": {
          "10": {"sub_type_reason": ["GPV3.1"], "sub_type": "", ...},
          "10А": {"sub_type_reason": ["GPV3.2"], ...}
        },
        "preset": { ...static weekly plan... },
        "fact":   { ...confirmed daily schedule... }
      }
```

---

## API reference

### `DtekClient(site_key, *, ajax_url, timeout, retry_attempts, retry_delay, session, session_factory, user_agent, csrf_token, discover_ajax_url)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `site_key` | `str` | `"kem"` | One of the keys in `DTEK_SITES` (`kem`, `krem`, `dnem`, `dem`, `oem`) |
| `ajax_url` | `str \| None` | `None` | Explicit AJAX URL (defaults to `base_url + /ua/ajax`) |
| `timeout` | `float` | `15` | Per-request timeout in seconds |
| `retry_attempts` | `int` | `3` | Number of attempts on 5xx errors |
| `retry_delay` | `float` | `1.0` | Base seconds between retries (linear back-off) |
| `session` | `aiohttp.ClientSession \| None` | `None` | Inject an external `aiohttp.ClientSession` |
| `session_factory` | `Callable[[], aiohttp.ClientSession] \| None` | `None` | Factory used to recreate the session if closed by the host |
| `user_agent` | `str \| None` | `None` | Custom `User-Agent` header |
| `csrf_token` | `str \| None` | `None` | Optional pre-configured CSRF token |
| `discover_ajax_url` | `bool` | `False` | Discover `ajaxUrl` from HTML `<meta>` tags before falling back to `/ua/ajax` |

### Methods

| Method | Returns | Description |
|---|---|---|
| `get_all_streets(*, refresh=False)` | `dict[str, list[str]]` | Complete settlement-to-streets dictionary for the region (cached on client) |
| `get_streets(city=None, *, refresh=False)` | `list[StreetSuggestion]` | Streets in a city (or all streets when `city=None` / on `kem`, cached) |
| `get_home_num(city, street)` | `HomeNumResponse` | All houses, groups, and schedules for a street |
| `get_group_by_address(city, street, house_number, *, response=None)` | `AddressResult` | Disconnection group for a specific address |
| `get_today_schedule(city, street, house_number, *, response=None)` | `dict[str, SlotStatus] \| None` | Today's slot map for one address |
| `get_tomorrow_schedule(city, street, house_number, *, response=None)` | `dict[str, SlotStatus] \| None` | Tomorrow's confirmed schedule slot map |
| `get_schedule_for_date(city, street, house_number, date, *, response=None)` | `dict[str, SlotStatus] \| None` | Confirmed schedule for a specific `datetime.date` |
| `get_available_fact_dates(response)` | `list[date]` | Calendar dates present in `HomeNumResponse.fact` (static method) |

### Key models

| Model | Purpose |
|---|---|
| `HouseEntry` | One house: `group_ids`, `primary_group`, `is_excluded`, `is_multi_group`, `has_current_outage`, `external_operator` |
| `HomeNumResponse` | Full AJAX response: `houses`, `preset`, `fact`, `find_house()`, schedule visibility flags |
| `PresetSchedule` | Static weekly plan: `groups[group_id].days[weekday].slots[tz_key]` |
| `FactSchedule` | Confirmed daily schedule: `get_group_today(group_id)`, `get_group_for_date(date, group_id)` |
| `FactDaySchedule` | One group on one day: `slots`, `outage_slot_count`, `day_date` |
| `SlotStatus` | `YES` / `NO` / `MAYBE` / `FIRST` / `SECOND` / `MFIRST` / `MSECOND` / `UNKNOWN` |
| `AddressResult` | `site_key`, `city`, `street`, `house_number`, `group_id`, `group_display_name` |
| `StreetSuggestion` | `name: str` — one street from `getStreets` |

### Exceptions

```text
DtekClientError                  <- base (status_code: int | None)
├── DtekConnectionError
│   ├── DtekTimeoutError         (timeout: float)
│   ├── DtekSSLError
│   └── DtekBlockedError         (WAF challenge page)
├── DtekAPIError
│   ├── DtekUnauthorizedError    (HTTP 401)
│   ├── DtekNotFoundError        (HTTP 404, path: str)
│   ├── DtekRateLimitError       (HTTP 429, retry_after: float | None)
│   └── DtekServerError          (HTTP 5xx)
├── DtekDataError                (JSON parse / validation failure, raw: object)
└── DtekSiteError                (unknown site_key / configuration error)
```

---

## Usage inside Home Assistant

In `manifest.json`:

```json
{
  "domain": "dtek_outage",
  "name": "DTEK Outage Schedule",
  "requirements": ["dtek-blackout-client==0.2.1"],
  "dependencies": []
}
```

In `coordinator.py`:

```python
import aiohttp
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from dtek_client import DtekClient

def create_dtek_session() -> aiohttp.ClientSession:
    return async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())

client = DtekClient(
    config["site_key"],
    session=create_dtek_session(),
    session_factory=create_dtek_session,
)

response = await client.get_home_num(config["city"], config["street"])
result = await client.get_group_by_address(
    city=config["city"],
    street=config["street"],
    house_number=config["house_number"],
    response=response,
)
slots = await client.get_today_schedule(
    city=config["city"],
    street=config["street"],
    house_number=config["house_number"],
    response=response,
)
```

### Development stub

```python
from dtek_client.stub_client import StubDtekClient as DtekClient

async with DtekClient("krem") as client:
    result = await client.get_group_by_address("м. Українка", "вул. Юності", "1")
    slots  = await client.get_today_schedule("м. Українка", "вул. Юності", "1")
```

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the developer guide.

```bash
git clone https://github.com/shed-crypto/dtek-blackout-client.git
cd dtek-blackout-client
poetry install
poetry run pytest
```

---

## License

[MIT](LICENSE) 2026 Rachenko
