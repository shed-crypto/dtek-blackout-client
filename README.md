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
Its regional subsidiaries operate separate websites that publish planned
disconnection schedules for cities and towns across Ukraine.

Unlike YASNO (which has a REST API), **DTEK sites use WordPress AJAX** — there
is no public API. This library reverse-engineers the AJAX protocol used by the
frontend JavaScript (`discon-schedule.js`) to provide a clean, fully-typed,
fully async Python interface.

### Supported regions

| `site_key` | English name | Ukrainian name | Coverage |
|---|---|---|---|
| `kem`  | DTEK Kyiv City Networks       | ДТЕК Київські електромережі    | Kyiv city and oblast (large towns) |
| `krem` | DTEK Kyiv Regional Networks   | ДТЕК Київські регіональні      | Kyiv oblast (smaller towns: Ukrainka, Obukhiv, Vyshhorod…) |
| `dnem` | DTEK Dnipro Networks          | ДТЕК Дніпровські електромережі | Dnipro, Dnipropetrovsk oblast |
| `dem`  | DTEK Donetsk Networks         | ДТЕК Донецькі електромережі    | Government-controlled Donetsk oblast |
| `oem`  | DTEK Odesa Networks           | ДТЕК Одеські електромережі     | Odesa, Odesa oblast |
| `zem`  | DTEK Zaporizhzhia Networks    | ДТЕК Запорізькі електромережі  | Zaporizhzhia |

Region names are also available programmatically — see `const.REGION_NAMES`,
`REGION_NAMES_EN`, and `REGION_NAMES_UA`.

---

## Features

- ✅ **Fully async** — built on `curl_cffi`, ready for Home Assistant's event loop
- ✅ **WAF-aware** — `browser_auth` module uses Playwright to bypass Incapsula/Imperva challenges
- ✅ **Auto-discovery** — finds the AJAX endpoint from `<meta name="ajaxUrl">` automatically; falls back through 5 regex patterns and a hardcoded path
- ✅ **Typed** — every model uses `pydantic` v2 with strict validation; all models are `frozen=True`
- ✅ **Resilient** — automatic retry with linear back-off on 5xx errors
- ✅ **Stub included** — `StubDtekClient` allows offline development without any network access
- ✅ **Tested** — 90%+ coverage, all HTTP calls mocked; no internet required in CI
- ✅ **Timezone-aware** — correctly handles Kyiv time (EEST) via zoneinfo; works on Windows thanks to tzdata integration.
---

## Installation

```bash
pip install dtek-blackout-client
```

Or with Poetry:

```bash
poetry add dtek-blackout-client
```

---

## Quick start

### Simple usage (no WAF)

```python
import asyncio
from dtek_client import DtekClient

async def main() -> None:
    async with DtekClient("krem") as client:

        # Get all streets in a city
        streets = await client.get_streets("м. Українка")
        print([s.name for s in streets])

        # Get all houses + groups for a street
        response = await client.get_home_num("м. Українка", "вул. Юності")
        for house, entry in sorted(response.houses.items()):
            status = "excluded" if entry.is_excluded else entry.primary_group
            print(f"  {house:6s} → {status}")

        # Find your group by address
        result = await client.get_group_by_address(
            city="м. Українка",
            street="вул. Юності",
            house_number="1",
        )
        print(result) 

asyncio.run(main())
```

### With WAF bypass (Playwright + curl_cffi)

DTEK sites are protected by Incapsula/Imperva WAF. For reliable access,
use `browser_auth` to obtain session cookies, then pass them to `curl_cffi`:

```python
import asyncio
from curl_cffi.requests import AsyncSession
from dtek_client import DtekClient
from dtek_client.browser_auth import get_cleared_cookies

async def main() -> None:
    base_url = "https://www.dtek-krem.com.ua"
    schedule_url = f"{base_url}/ua/shutdowns"

    # Step 1: get WAF-cleared cookies and CSRF token via a real browser
    cookies, csrf_token = await get_cleared_cookies(schedule_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "uk,en;q=0.9",
        "Origin": base_url,
        "Referer": schedule_url,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token

    # Step 2: create a curl_cffi session that impersonates Chrome
    session = AsyncSession(
        timeout=15.0,
        headers=headers,
        cookies=cookies,
        impersonate="chrome120",
    )

    # Step 3: pass the session to DtekClient (skip ajax_url discovery)
    async with DtekClient("krem", ajax_url=f"{base_url}/ua/ajax", session=session) as client:
        streets = await client.get_streets("м. Українка")
        for s in streets[:10]:
            print(s.name)

asyncio.run(main())
```

---

## How DTEK sites work (protocol overview)

```
1. GET https://www.dtek-kem.com.ua/ua/shutdowns
   → HTML page contains <meta name="ajaxUrl" content="/ua/ajax">
     (may be a relative path — the client resolves it against base_url)

2. POST <ajaxUrl>  (application/x-www-form-urlencoded)
   method=getStreets
   → {"result": true, "streets": {"м. Україна": ["вул. Юності", ...]}}

3. POST <ajaxUrl>
   method=getHomeNum
   data[0][name]=city    & data[0][value]=м. Україна
   data[1][name]=street  & data[1][value]=вул. Юності
   data[2][name]=updateFact & data[2][value]=<timestamp>
   → {
       "result": true,
       "data": {
         "10": {"sub_type_reason": ["GPV3.1"], "sub_type": "", ...},
         "10А": {"sub_type_reason": ["GPV3.2"], ...}
       },
       "preset": { ...static weekly plan... },
       "fact":   { ...today's confirmed schedule... }
     }
```

The client handles step 1 automatically and caches the result.
Discovery tries 5 regex patterns (meta tag, JS variable, WP AJAX object) and
falls back to `base_url + /ua/ajax` if none match.

---

## API reference

### `DtekClient(site_key, *, ajax_url, timeout, retry_attempts, retry_delay, session)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `site_key` | `str` | `"kem"` | One of the keys in `DTEK_SITES` |
| `ajax_url` | `str \| None` | `None` | Skip discovery and use this URL directly |
| `timeout` | `float` | `15` | Per-request timeout in seconds |
| `retry_attempts` | `int` | `3` | Number of retries on 5xx errors |
| `retry_delay` | `float` | `1.0` | Seconds between retries (linear back-off) |
| `session` | `AsyncSession \| None` | `None` | Inject an existing `curl_cffi.requests.AsyncSession` |

### Methods

| Method | Returns | Description |
|---|---|---|
| `get_streets(city)` | `list[StreetSuggestion]` | All streets in a city |
| `get_home_num(city, street)` | `HomeNumResponse` | All houses + groups + schedule for a street |
| `get_group_by_address(city, street, house_number)` | `AddressResult` | Group for a specific address |
| `get_today_schedule(city, street, house_number)` | `dict[str, SlotStatus] \| None` | Today's slot map for one address |
| `get_tomorrow_schedule(city, street, house)` | `dict \| None` | Shortcut for tomorrow's confirmed schedule |
| `get_available_fact_dates(response)` | `list[date]` | Discover which dates have published schedules (static method) |
| `get_schedule_for_date(city, street, house, date)` | `dict \| None` | Get confirmed schedule for a specific datetime.date |

### Key models

| Model | Purpose |
|---|---|
| `HouseEntry` | One house: `group_ids`, `primary_group`, `is_excluded`, `is_multi_group`, `has_current_outage` |
| `HomeNumResponse` | Full AJAX response: `houses`, `preset`, `fact`, schedule visibility flags |
| `PresetSchedule` | Static weekly plan: `groups[group_id].days[weekday].slots[tz_key]` |
| `FactSchedule` | Confirmed daily schedule: `get_group_today(group_id)` → `dict[str, SlotStatus]` |
| `FactDaySchedule` | One group on one day: `slots`, `outage_slot_count`, `day_date` |
| `SlotStatus` | `YES` / `NO` / `MAYBE` / `FIRST` / `SECOND` / `MFIRST` / `MSECOND` / `UNKNOWN` |
| `AddressResult` | `site_key`, `city`, `street`, `house_number`, `group_id`, `group_display_name` |
| `StreetSuggestion` | `name: str` — one street from `getStreets` |

### `SlotStatus` properties

```python
SlotStatus.NO.has_outage          # True  — definitely no electricity
SlotStatus.FIRST.has_outage       # True  — outage in first half of slot (~15 min)
SlotStatus.MAYBE.has_outage       # False — not definite
SlotStatus.MAYBE.may_have_outage  # True  — possible or definite outage
SlotStatus.YES.may_have_outage    # False — electricity guaranteed
SlotStatus("something_new")       # → SlotStatus.UNKNOWN  (never raises)
```

### Region name constants

```python
from dtek_client.const import REGION_NAMES, REGION_NAMES_EN, REGION_NAMES_UA

print(REGION_NAMES["krem"])     # "DTEK Kyiv Regional Networks / ДТЕК Київські регіональні (Київська обл.)"
print(REGION_NAMES_EN["krem"])  # "DTEK Kyiv Regional Networks"
print(REGION_NAMES_UA["krem"])  # "ДТЕК Київські регіональні (Київська обл.)"
```

### Exceptions

```
DtekClientError                  ← base (status_code: int | None)
├── DtekConnectionError
│   ├── DtekTimeoutError         (timeout: float)
│   └── DtekSSLError
├── DtekAPIError
│   ├── DtekUnauthorizedError    (HTTP 401)
│   ├── DtekNotFoundError        (HTTP 404, path: str)
│   ├── DtekRateLimitError       (HTTP 429, retry_after: float | None)
│   └── DtekServerError          (HTTP 5xx)
├── DtekDataError                (JSON parse / validation failure, raw: object)
└── DtekSiteError                (unknown site_key / ajaxUrl not found)
```

---

## Usage inside Home Assistant

In `manifest.json`:

```json
{
  "domain": "dtek_outage",
  "name": "DTEK Outage Schedule",
  "requirements": ["dtek-blackout-client==0.1.0"],
  "dependencies": []
}
```

In `coordinator.py`:

```python
from dtek_client import DtekClient

# DtekClient manages its own curl_cffi session.
# Do NOT pass hass.helpers.aiohttp_client here — use the default session.
client = DtekClient(config["site_key"])
await client.connect()

result = await client.get_group_by_address(
    city=config["city"],
    street=config["street"],
    house_number=config["house_number"],
)
slots = await client.get_today_schedule(
    city=config["city"],
    street=config["street"],
    house_number=config["house_number"],
)
```

### Development stub

```python
# Swap one line — start immediately without network access:
from dtek_client.stub_client import StubDtekClient as DtekClient

# Everything else stays identical
async with DtekClient("krem") as client:
    result = await client.get_group_by_address("м. Українка", "вул. Юності", "1")
    slots  = await client.get_today_schedule("м. Українка", "вул. Юності", "1")
```

The stub returns realistic data for `м. Українка` / `м. Обухів` with groups
`GPV3.1`, `GPV3.2`, `GPV4.1` and a matching preset + today's fact schedule.

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full developer guide.

```bash
git clone https://github.com/shed-crypto/dtek-blackout-client.git
cd dtek-blackout-client
poetry install
poetry run pytest
```

Expected output:
```
174 passed in 6.41s
Total coverage: 99.83%
```

---

## License

[MIT](LICENSE) © 2026 Rachenko

---
---

# dtek-blackout-client

> Асинхронний Python-клієнт для сайтів регіональних графіків відключень електроенергії **DTEK**  

[![CI](https://github.com/shed-crypto/dtek-blackout-client/actions/workflows/ci.yml/badge.svg)](https://github.com/shed-crypto/dtek-blackout-client/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/dtek-blackout-client.svg)](https://pypi.org/project/dtek-blackout-client/)
[![Python versions](https://img.shields.io/pypi/pyversions/dtek-blackout-client.svg)](https://pypi.org/project/dtek-blackout-client/)
[![codecov](https://codecov.io/gh/shed-crypto/dtek-blackout-client/branch/main/graph/badge.svg)](https://codecov.io/gh/shed-crypto/dtek-blackout-client)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Що таке DTEK?

[DTEK](https://dtek.com/) — найбільша приватна енергетична компанія України.
Її регіональні дочірні підприємства підтримують окремі сайти, що публікують
плановані графіки відключень для міст і селищ по всій Україні.

На відміну від YASNO (яке має REST API), **сайти DTEK використовують WordPress AJAX** —
публічного API не існує. Ця бібліотека реінжинірить AJAX-протокол,
що використовується фронтендовим JavaScript (`discon-schedule.js`),
і надає чистий, повністю типізований, повністю асинхронний Python-інтерфейс.

### Підтримувані регіони

| `site_key` | Назва англійською | Назва українською | Охоплення |
|---|---|---|---|
| `kem`  | DTEK Kyiv City Networks       | ДТЕК Київські електромережі    | Місто Київ та область (великі міста) |
| `krem` | DTEK Kyiv Regional Networks   | ДТЕК Київські регіональні      | Київська область (менші міста: Українка, Обухів, Вишгород…) |
| `dnem` | DTEK Dnipro Networks          | ДТЕК Дніпровські електромережі | Дніпро, Дніпропетровська область |
| `dem`  | DTEK Donetsk Networks         | ДТЕК Донецькі електромережі    | Підконтрольна уряду частина Донецької обл. |
| `oem`  | DTEK Odesa Networks           | ДТЕК Одеські електромережі     | Одеса, Одеська область |
| `zem`  | DTEK Zaporizhzhia Networks    | ДТЕК Запорізькі електромережі  | Запоріжжя |

Назви регіонів також доступні програмно — див. `const.REGION_NAMES`,
`REGION_NAMES_EN` та `REGION_NAMES_UA`.

---

## Можливості

- ✅ **Повністю асинхронний** — побудований на `curl_cffi`, готовий до event loop Home Assistant
- ✅ **Захист від WAF** — модуль `browser_auth` використовує Playwright для обходу Incapsula/Imperva
- ✅ **Автовиявлення** — знаходить AJAX-ендпоінт з `<meta name="ajaxUrl">` автоматично; якщо не вдається — перебирає 5 регулярних виразів та хардкодений шлях
- ✅ **Типізований** — усі моделі використовують `pydantic` v2 зі строгою валідацією; всі моделі — `frozen=True`
- ✅ **Стійкий** — автоматичний повтор із лінійним відступом при помилках 5xx
- ✅ **Стаб включено** — `StubDtekClient` дозволяє вести розробку офлайн без доступу до мережі
- ✅ **Протестований** — покриття 90%+, всі HTTP-виклики замоковані; CI не потребує Інтернету
- ✅ **З урахуванням часових поясів** — коректно обробляє київський час (EEST) через zoneinfo; працює у Windows завдяки інтеграції з tzdata.

---

## Встановлення

```bash
pip install dtek-blackout-client
```

Або через Poetry:

```bash
poetry add dtek-blackout-client
```

---

## Швидкий старт

### Простий приклад (без WAF)

```python
import asyncio
from dtek_client import DtekClient

async def main() -> None:
    async with DtekClient("krem") as client:

        # Отримати всі вулиці міста
        streets = await client.get_streets("м. Українка")
        print([s.name for s in streets])

        # Отримати всі будинки + групи для вулиці
        response = await client.get_home_num("м. Українка", "вул. Юності")
        for house, entry in sorted(response.houses.items()):
            status = "excluded" if entry.is_excluded else entry.primary_group
            print(f"  {house:6s} → {status}")

        # Знайти свою чергу за адресою
        result = await client.get_group_by_address(
            city="м. Українка",
            street="вул. Юності",
            house_number="1",
        )
        print(result)  # м. Українка, вул. Юності, 1 → Черга планових відключень 3.1

asyncio.run(main())
```

### З обходом WAF (Playwright + curl_cffi)

Сайти DTEK захищені WAF Incapsula/Imperva. Для надійного доступу
використовуйте `browser_auth` для отримання cookies сесії, а потім
передайте їх у `curl_cffi`:

```python
import asyncio
from curl_cffi.requests import AsyncSession
from dtek_client import DtekClient
from dtek_client.browser_auth import get_cleared_cookies

async def main() -> None:
    base_url = "https://www.dtek-krem.com.ua"
    schedule_url = f"{base_url}/ua/shutdowns"

    # Крок 1: отримати cookies та CSRF-токен через реальний браузер
    cookies, csrf_token = await get_cleared_cookies(schedule_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "uk,en;q=0.9",
        "Origin": base_url,
        "Referer": schedule_url,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token

    # Крок 2: створити curl_cffi-сесію, що імітує Chrome
    session = AsyncSession(
        timeout=15.0,
        headers=headers,
        cookies=cookies,
        impersonate="chrome120",
    )

    # Крок 3: передати сесію до DtekClient (пропустити виявлення ajax_url)
    async with DtekClient("krem", ajax_url=f"{base_url}/ua/ajax", session=session) as client:
        streets = await client.get_streets("м. Українка")
        for s in streets[:10]:
            print(s.name)

asyncio.run(main())
```

---

## Як працюють сайти DTEK (огляд протоколу)

```
1. GET https://www.dtek-kem.com.ua/ua/shutdowns
   → HTML-сторінка містить <meta name="ajaxUrl" content="/ua/ajax">
     (може бути відносний шлях — клієнт розв'язує його відносно base_url)

2. POST <ajaxUrl>  (application/x-www-form-urlencoded)
   method=getStreets
   → {"result": true, "streets": {"м. Україна": ["вул. Юності", ...]}}

3. POST <ajaxUrl>
   method=getHomeNum
   data[0][name]=city    & data[0][value]=м. Україна
   data[1][name]=street  & data[1][value]=вул. Юності
   data[2][name]=updateFact & data[2][value]=<timestamp>
   → {
       "result": true,
       "data": {
         "10": {"sub_type_reason": ["GPV3.1"], "sub_type": "", ...},
         "10А": {"sub_type_reason": ["GPV3.2"], ...}
       },
       "preset": { ...статичний тижневий план... },
       "fact":   { ...підтверджений графік на сьогодні... }
     }
```

Клієнт виконує крок 1 автоматично і кешує результат.
Виявлення перебирає 5 регулярних виразів (мета-тег, JS-змінна, WP AJAX-об'єкт)
і відступає до `base_url + /ua/ajax`, якщо нічого не знайдено.

---

## Довідка по API

### `DtekClient(site_key, *, ajax_url, timeout, retry_attempts, retry_delay, session)`

| Параметр | Тип | За замовчуванням | Опис |
|---|---|---|---|
| `site_key` | `str` | `"kem"` | Один із ключів у `DTEK_SITES` |
| `ajax_url` | `str \| None` | `None` | Пропустити виявлення і використати цей URL напряму |
| `timeout` | `float` | `15` | Тайм-аут запиту в секундах |
| `retry_attempts` | `int` | `3` | Кількість спроб при помилках 5xx |
| `retry_delay` | `float` | `1.0` | Секунди між спробами (лінійний відступ) |
| `session` | `AsyncSession \| None` | `None` | Передати існуючу `curl_cffi.requests.AsyncSession` |

### Методи

| Метод | Повертає | Опис |
|---|---|---|
| `get_streets(city)` | `list[StreetSuggestion]` | Всі вулиці міста |
| `get_home_num(city, street)` | `HomeNumResponse` | Всі будинки + групи + графік для вулиці |
| `get_group_by_address(city, street, house_number)` | `AddressResult` | Черга для конкретної адреси |
| `get_today_schedule(city, street, house_number)` | `dict[str, SlotStatus] \| None` | Карта слотів на сьогодні для однієї адреси |
| `get_tomorrow_schedule(city, street, house)` | `dict \| None` | Скорочений шлях до підтвердженого розкладу на завтра |
| `get_available_fact_dates(response)` | `list[date]` | Дізнайтеся, на які дати опубліковано розклади (статичний метод) |
| `get_schedule_for_date(city, street, house, date)` | `dict \| None` | Отримати підтверджений розклад на певну дату/час |

### Основні моделі

| Модель | Призначення |
|---|---|
| `HouseEntry` | Один будинок: `group_ids`, `primary_group`, `is_excluded`, `is_multi_group`, `has_current_outage` |
| `HomeNumResponse` | Повна відповідь AJAX: `houses`, `preset`, `fact`, прапорці видимості графіка |
| `PresetSchedule` | Статичний тижневий план: `groups[group_id].days[weekday].slots[tz_key]` |
| `FactSchedule` | Підтверджений добовий графік: `get_group_today(group_id)` → `dict[str, SlotStatus]` |
| `FactDaySchedule` | Одна група на один день: `slots`, `outage_slot_count`, `day_date` |
| `SlotStatus` | `YES` / `NO` / `MAYBE` / `FIRST` / `SECOND` / `MFIRST` / `MSECOND` / `UNKNOWN` |
| `AddressResult` | `site_key`, `city`, `street`, `house_number`, `group_id`, `group_display_name` |
| `StreetSuggestion` | `name: str` — одна вулиця з `getStreets` |

### Властивості `SlotStatus`

```python
SlotStatus.NO.has_outage          # True  — електрики точно немає
SlotStatus.FIRST.has_outage       # True  — відключення в першій половині слоту (~15 хв)
SlotStatus.MAYBE.has_outage       # False — не визначено
SlotStatus.MAYBE.may_have_outage  # True  — можливе або точне відключення
SlotStatus.YES.may_have_outage    # False — електрика гарантована
SlotStatus("something_new")       # → SlotStatus.UNKNOWN  (ніколи не кидає виняток)
```

### Константи назв регіонів

```python
from dtek_client.const import REGION_NAMES, REGION_NAMES_EN, REGION_NAMES_UA

print(REGION_NAMES["krem"])     # "DTEK Kyiv Regional Networks / ДТЕК Київські регіональні (Київська обл.)"
print(REGION_NAMES_EN["krem"])  # "DTEK Kyiv Regional Networks"
print(REGION_NAMES_UA["krem"])  # "ДТЕК Київські регіональні (Київська обл.)"
```

### Винятки

```
DtekClientError                  ← базовий (status_code: int | None)
├── DtekConnectionError
│   ├── DtekTimeoutError         (timeout: float)
│   └── DtekSSLError
├── DtekAPIError
│   ├── DtekUnauthorizedError    (HTTP 401)
│   ├── DtekNotFoundError        (HTTP 404, path: str)
│   ├── DtekRateLimitError       (HTTP 429, retry_after: float | None)
│   └── DtekServerError          (HTTP 5xx)
├── DtekDataError                (помилка парсингу JSON / валідації, raw: object)
└── DtekSiteError                (невідомий site_key / ajaxUrl не знайдено)
```

---

## Використання в Home Assistant

У `manifest.json`:

```json
{
  "domain": "dtek_outage",
  "name": "DTEK Outage Schedule",
  "requirements": ["dtek-blackout-client==0.1.0"],
  "dependencies": []
}
```

У `coordinator.py`:

```python
from dtek_client import DtekClient

# DtekClient керує власною curl_cffi-сесією.
# НЕ передавайте сюди hass.helpers.aiohttp_client — використовуйте сесію за замовчуванням.
client = DtekClient(config["site_key"])
await client.connect()

result = await client.get_group_by_address(
    city=config["city"],
    street=config["street"],
    house_number=config["house_number"],
)
slots = await client.get_today_schedule(
    city=config["city"],
    street=config["street"],
    house_number=config["house_number"],
)
```

### Стаб для розробки

```python
# Змініть один рядок — починайте розробку офлайн без доступу до мережі:
from dtek_client.stub_client import StubDtekClient as DtekClient

# Все інше залишається ідентичним
async with DtekClient("krem") as client:
    result = await client.get_group_by_address("м. Українка", "вул. Юності", "1")
    slots  = await client.get_today_schedule("м. Українка", "вул. Юності", "1")
```

Стаб повертає реалістичні дані для `м. Українка` / `м. Обухів` з групами
`GPV3.1`, `GPV3.2`, `GPV4.1` та відповідним preset + фактичним графіком на сьогодні.

---

## Розробка

Повний гайд розробника — у [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/shed-crypto/dtek-blackout-client.git
cd dtek-blackout-client
poetry install
poetry run pytest
```

Очікуваний вивід:
```
174 passed in 6.41s
Total coverage: 99.83%
```

---

## Ліцензія

[MIT](LICENSE) © 2026 Rachenko