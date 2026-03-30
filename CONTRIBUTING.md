# Contributing to dtek-blackout-client

Developer guide: setup → development → testing → publishing.

---

## Contents

1. [What we are building and how it works](#1-what-we-are-building-and-how-it-works)
2. [First run](#2-first-run)
3. [Project structure](#3-project-structure)
4. [Manual testing](#4-manual-testing)
5. [Running automated tests](#5-running-automated-tests)
6. [Code quality tools](#6-code-quality-tools)
7. [Sharing the library with teammates (Stub)](#7-sharing-the-library-with-teammates-stub)
8. [Publishing to PyPI](#8-publishing-to-pypi)
9. [Setting up CI/CD on GitHub](#9-setting-up-cicd-on-github)
10. [Common errors](#10-common-errors)
11. [Project defence checklist](#11-project-defence-checklist)

---

## 1. What we are building and how it works

```
[DTEK site] ←→ [dtek-blackout-client] ←→ [Home Assistant integration]
(WordPress)     (this library)             (Home Assistant integration)
```

DTEK **has no public REST API**. Their sites are WordPress applications where
the browser communicates with the server over AJAX. We implement the same
protocol that `discon-schedule.js` uses on their site.

### AJAX protocol (3 steps)

**Step 1 — find the endpoint URL:**
```
GET https://www.dtek-kem.com.ua/ua/shutdowns
→ HTML contains: <meta name="ajaxUrl" content="/ua/ajax">
  (content may be a relative path — the client resolves it against base_url)
```

**Step 2 — get streets for a city:**
```
POST <ajaxUrl>
  method=getStreets
→ {"result": true, "streets": {"м. Україна": ["вул. Юності", ...]}}
```

**Step 3 — get houses and groups:**
```
POST <ajaxUrl>
  method=getHomeNum
  data[0][name]=city   & data[0][value]=м. Україна
  data[1][name]=street & data[1][value]=вул. Юності
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

### What are `preset` and `fact`?

- **`preset`** — static weekly outage plan (7 days × N groups × 48 slots).
  Each slot: `"yes"` (electricity) or `"no"` (outage).

- **`fact`** — the confirmed NPC Ukrenerho schedule for today and tomorrow.
  Updated throughout the day. May contain `"maybe"`, `"first"`, `"second"` etc.

### WAF protection

DTEK sites are protected by Incapsula/Imperva WAF. The client handles this
in two ways:

1. **Automatic warm-up GET** — on `connect()`, the client fetches the schedule
   page once to acquire WAF cookies before making POST requests.
2. **`browser_auth` module** — for sites where the automatic warm-up is not
   enough, use `get_cleared_cookies()` to launch a headless Playwright browser
   that solves the JS challenge and returns ready-to-use cookies + CSRF token.

---

## 2. First run

### Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) |
| Poetry | 1.8+ | `pip install poetry` |
| Git | any | [git-scm.com](https://git-scm.com) |
| Playwright (optional) | latest | `poetry run playwright install chromium` |

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/shed-crypto/dtek-blackout-client.git
cd dtek-blackout-client

# 2. Install all dependencies (including dev)
poetry install

# 3. (Optional) install Playwright browser for WAF bypass
poetry run playwright install chromium

# 4. Verify everything works
poetry run pytest
```

Expected output:
```
174 passed in 6.41s
Total coverage: 99.83%
```

---

## 3. Project structure

```
dtek-blackout-client/
│
├── dtek_client/                   ← installable package
│   ├── __init__.py                ← public API (what gets imported externally)
│   ├── client.py                  ← DtekClient — main async HTTP client
│   ├── models.py                  ← Pydantic v2 models for all responses
│   ├── exceptions.py              ← exception hierarchy
│   ├── const.py                   ← URLs for all 6 DTEK sites, slot constants,
│   │                                 REGION_NAMES / REGION_NAMES_EN / REGION_NAMES_UA
│   ├── stub_client.py             ← StubDtekClient (hardcoded data, no network)
│   └── browser_auth.py            ← Playwright WAF bypass helper
│
├── tests/
│   ├── conftest.py                ← shared pytest fixtures + make_mock_response()
│   ├── test_client.py             ← DtekClient tests (all HTTP mocked via curl_cffi)
│   ├── test_models.py             ← Pydantic model tests
│   ├── test_exceptions.py         ← exception hierarchy tests
│   ├── test_stub_client.py        ← StubDtekClient tests
│   └── fixtures/
│       ├── home_num_response.json ← realistic getHomeNum response fixture
│       └── streets_response.json  ← realistic getStreets response fixture
│
├── .github/workflows/
│   ├── ci.yml                     ← lint + tests on every PR (Python 3.11 + 3.12)
│   └── publish.yml                ← build + PyPI on git tag
│
├── manual_test.py                 ← manual integration test (do not commit)
├── pyproject.toml                 ← Poetry + mypy + ruff + black + pytest config
├── README.md                      ← user-facing documentation
└── CONTRIBUTING.md                ← this file
```

### Key design decisions

- **`curl_cffi`** is used instead of `aiohttp` because it can impersonate a
  real Chrome browser (`impersonate="chrome120"`), which is necessary to pass
  TLS fingerprinting checks on DTEK sites.
- All Pydantic models are `frozen=True` — safe to share between coroutines.
- `_handle_response()` is **synchronous** — `curl_cffi` responses expose
  `.json()` as a plain method, not a coroutine.
- `StubDtekClient` uses `model_construct()` to bypass model validators (which
  expect raw AJAX dicts), so it can build models from pre-constructed objects.

---

## 4. Manual testing

`manual_test.py` in the project root demonstrates the full WAF bypass flow
for `krem` (Kyiv Regional) and `oem` (Odesa). Run it locally:

```bash
poetry run python manual_test.py
```

> If the DTEK site is temporarily unavailable, replace `DtekClient` with
> `StubDtekClient` in a single import line — all methods are identical.

For a minimal manual test without WAF bypass:

```python
import asyncio
from dtek_client import DtekClient

async def main() -> None:
    async with DtekClient("krem") as client:
        streets = await client.get_streets("м. Українка")
        for s in streets:
            print(s.name)

        response = await client.get_home_num("м. Українка", "вул. Юності")
        for house, entry in sorted(response.houses.items()):
            status = "excluded" if entry.is_excluded else entry.primary_group
            print(f"  {house:6s} → {status}")

asyncio.run(main())
```

---

## 5. Running automated tests

```bash
# All tests with coverage:
poetry run pytest

# One file:
poetry run pytest tests/test_models.py -v

# Tests matching a keyword:
poetry run pytest -k "TestGetGroupByAddress" -v

# Coverage as HTML (open in browser):
poetry run pytest --cov-report=html
open htmlcov/index.html
```

> Tests **never make real HTTP requests**. All `_post()` and `_get_ajax_url()`
> calls are mocked via `unittest.mock.AsyncMock` and the `make_mock_response()`
> helper in `conftest.py`. Tests pass offline.

### Writing new tests

Use the `make_mock_response()` helper from `conftest.py` to create curl_cffi-
compatible mock responses:

```python
from tests.conftest import make_mock_response

resp = make_mock_response(status_code=200, json_data={"result": True, "data": {}})
# resp.status_code → 200
# resp.json()      → {"result": True, "data": {}}
# resp.headers     → {}
```

Note: `_handle_response()` is a **synchronous** method — do not `await` it in tests.

---

## 6. Code quality tools

```bash
# Ruff — linter (replaces flake8 + isort)
poetry run ruff check dtek_client/

# Black — formatting check (no changes)
poetry run black --check dtek_client/ tests/

# Black — auto-fix formatting
poetry run black dtek_client/ tests/

# mypy — strict static type checking
poetry run mypy dtek_client/
```

Run all at once:

```bash
poetry run ruff check dtek_client/ && \
poetry run black --check dtek_client/ tests/ && \
poetry run mypy dtek_client/
```

---

## 7. Sharing the library with teammates (Stub)

`StubDtekClient` is a drop-in replacement that returns hardcoded but realistic
data — no network calls, no site scraping.

A teammate needs to change **one import line**:

```python
# During development — use the stub:
from dtek_client.stub_client import StubDtekClient as DtekClient

# When the real client is ready — revert to:
from dtek_client import DtekClient
```

Everything else stays **identical**.

What the stub returns:

| Method | Data |
|---|---|
| `get_streets("м. Українка")` | 4 streets |
| `get_home_num("м. Українка", "вул. Юності")` | 9 houses with groups GPV3.1, GPV3.2, GPV4.1 |
| `get_group_by_address("м. Українка", "вул. Юності", "1/1")` | GPV3.2 |
| `get_today_schedule("м. Українка", "вул. Юності", "1")` | Slots 1–8 and 37–44 = `NO` (outage) |

---

## 8. Publishing to PyPI

### One-time setup

1. Register on [pypi.org](https://pypi.org) and [test.pypi.org](https://test.pypi.org)
2. Verify that the name `dtek-blackout-client` is available

### Manual publish steps

```bash
# 1. Update the version in two places:
#    pyproject.toml          → version = "0.1.1"
#    dtek_client/__init__.py → __version__ = "0.1.1"

# 2. Build the package:
poetry build
# produces:
#   dist/dtek_blackout_client-0.1.1.tar.gz
#   dist/dtek_blackout_client-0.1.1-py3-none-any.whl

# 3. Verify the package:
pip install twine
twine check dist/*

# 4. Publish to TestPyPI first (safe):
twine upload --repository testpypi dist/*
# Verify: https://test.pypi.org/project/dtek-blackout-client/
pip install --index-url https://test.pypi.org/simple/ dtek-blackout-client
python3 -c "from dtek_client import DtekClient; print('OK')"

# 5. Publish to PyPI:
twine upload dist/*
```

### Automated publish via GitHub Actions

Just create a tag — everything else is automatic:

```bash
git add pyproject.toml dtek_client/__init__.py
git commit -m "chore: bump version to 0.1.1"
git tag v0.1.1
git push origin main --tags
```

`publish.yml` automatically: lint → test → build → TestPyPI → PyPI → GitHub Release.

---

## 9. Setting up CI/CD on GitHub

### Step 1 — push the code

```bash
git init
git add .
git commit -m "feat: initial release of dtek-blackout-client"
git branch -M main
git remote add origin https://github.com/shed-crypto/dtek-blackout-client.git
git push -u origin main
```

### Step 2 — configure Trusted Publishing on PyPI

On **pypi.org** → Account Settings → Publishing → Add publisher:
- Project name: `dtek-blackout-client`
- Owner: `shed-crypto`
- Repository: `dtek-blackout-client`
- Workflow: `publish.yml`
- Environment: `pypi`

Repeat on **test.pypi.org** with environment `testpypi`.

### Step 3 — GitHub Environments

GitHub → Settings → Environments → Create:
- `pypi`
- `testpypi`

### Step 4 — Codecov (optional)

1. Sign in to [codecov.io](https://codecov.io) via GitHub OAuth
2. Enable the repository
3. Add `CODECOV_TOKEN` to GitHub Secrets

---

## 10. Common errors

### `DtekSiteError: Unknown site_key`
```python
# Wrong:
client = DtekClient("kyiv")

# Correct — use a site_key from DTEK_SITES:
client = DtekClient("kem")   # DTEK Kyiv City Networks
client = DtekClient("krem")  # DTEK Kyiv Regional Networks
```

### `DtekConnectionError: Session not open`
```python
# Wrong:
client = DtekClient("kem")
streets = await client.get_streets("м. Українка")  # ERROR

# Correct:
async with DtekClient("kem") as client:
    streets = await client.get_streets("м. Українка")
```

### `DtekNotFoundError: House '10' not found`
House numbers in the DTEK database may differ from postal addresses.
First call `get_home_num()` and inspect `response.available_houses`.

### Incapsula WAF blocks the request
The site returned a JS challenge page instead of real HTML. Two options:

```python
# Option A: use browser_auth to get cookies
from dtek_client.browser_auth import get_cleared_cookies
cookies, csrf_token = await get_cleared_cookies("https://www.dtek-krem.com.ua/ua/shutdowns")

# Option B: open the page in a real browser, copy the ajaxUrl from DevTools
# Network → XHR → look for a POST to /ua/ajax or /wp-admin/admin-ajax.php
client = DtekClient("krem", ajax_url="https://www.dtek-krem.com.ua/ua/ajax")
```

### `pydantic.ValidationError` in tests
Check that the fixture JSON matches the real site response structure.
Run `manual_test.py` and compare.

### mypy complains about types
```bash
poetry run mypy dtek_client/ --show-error-codes
# Use type: ignore[...] only as a last resort — prefer fixing the type
```

### Tests fail with `AttributeError: 'MagicMock' object has no attribute 'status_code'`
The client now uses `curl_cffi`, which exposes `.status_code` (not `.status`).
Use `make_mock_response()` from `conftest.py` instead of building mocks manually.

---

## 11. Project defence checklist

### Repository
- [ ] Repository is public on GitHub
- [ ] Regular commits with Conventional Commit messages (`feat:`, `fix:`, `test:`, `docs:`)
- [ ] `README.md` with English description, examples, and region table
- [ ] `CONTRIBUTING.md` (this file) — Developer Guide

### CI/CD — green badges
- [ ] `ci.yml` — green on GitHub ✅ (runs on Python 3.11 + 3.12)
- [ ] Coverage badge > 90%
- [ ] `publish.yml` — configured with Trusted Publishing

### Code quality
- [ ] `poetry run pytest` — all tests pass
- [ ] `poetry run pytest --cov` — coverage > 90%
- [ ] `poetry run ruff check dtek_client/` — no errors
- [ ] `poetry run black --check dtek_client/ tests/` — no errors
- [ ] `poetry run mypy dtek_client/` — no errors

### PyPI
- [ ] `pip install dtek-blackout-client` — works
- [ ] `from dtek_client import DtekClient` — imports correctly

### Team integration
- [ ] HA integration imports `StubDtekClient` and can start coding immediately
- [ ] `get_group_by_address()` returns real data from the live site
- [ ] Code review — comments left on PRs

### What to demonstrate at defence
1. GitHub → green CI badges
2. `poetry run pytest` → 90%+ coverage in terminal
3. `manual_test.py` → real data from `dtek-krem.com.ua`
4. `pypi.org/project/dtek-blackout-client` → published package page
5. Teammate's HA code → `from dtek_client import DtekClient` working

---

## Contributing

### Branching

```bash
git checkout -b feat/add-check-update-method
```

### Commit style (Conventional Commits)

```
feat: add checkDisconUpdate polling method
fix: handle empty streets list from getStreets
test: cover DtekSiteError on missing ajaxUrl meta
docs: update README with WAF bypass example
chore: bump curl-cffi to 0.14.1
```

### Pull request flow

1. Branch from `main`
2. Write tests for new code
3. `poetry run pytest` — green
4. Linters — no errors
5. Open a PR to `main`

---

*This file is the Developer Guide (Etap 4 of the technical specification).
All comments in source code are in English; Ukrainian appears only in string
values (city names, schedule labels) where it reflects the real DTEK API.*

---
---

# Участь у розробці dtek-blackout-client

Гайд розробника: налаштування → розробка → тестування → публікація.

---

## Зміст

1. [Що ми будуємо і як це працює](#1-що-ми-будуємо-і-як-це-працює)
2. [Перший запуск](#2-перший-запуск)
3. [Структура проекту](#3-структура-проекту)
4. [Ручне тестування](#4-ручне-тестування)
5. [Запуск автоматичних тестів](#5-запуск-автоматичних-тестів)
6. [Інструменти якості коду](#6-інструменти-якості-коду)
7. [Передача бібліотеки колегам (Стаб)](#7-передача-бібліотеки-колегам-стаб)
8. [Публікація на PyPI](#8-публікація-на-pypi)
9. [Налаштування CI/CD на GitHub](#9-налаштування-cicd-на-github)
10. [Типові помилки](#10-типові-помилки)
11. [Чекліст захисту проекту](#11-чекліст-захисту-проекту)

---

## 1. Що ми будуємо і як це працює

```
[Сайт DTEK] ←→ [dtek-blackout-client] ←→ [Інтеграція Home Assistant]
(WordPress)      (ця бібліотека)            (інтеграція Home Assistant)
```

DTEK **не має публічного REST API**. Їхні сайти — WordPress-застосунки, де
браузер спілкується з сервером через AJAX. Ми реалізуємо той самий протокол,
що використовує `discon-schedule.js` на їхньому сайті.

### AJAX-протокол (3 кроки)

**Крок 1 — знайти URL ендпоінту:**
```
GET https://www.dtek-kem.com.ua/ua/shutdowns
→ HTML містить: <meta name="ajaxUrl" content="/ua/ajax">
  (вміст може бути відносним шляхом — клієнт розв'язує його відносно base_url)
```

**Крок 2 — отримати вулиці міста:**
```
POST <ajaxUrl>
  method=getStreets
→ {"result": true, "streets": {"м. Україна": ["вул. Юності", ...]}}
```

**Крок 3 — отримати будинки та групи:**
```
POST <ajaxUrl>
  method=getHomeNum
  data[0][name]=city   & data[0][value]=м. Україна
  data[1][name]=street & data[1][value]=вул. Юності
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

### Що таке `preset` і `fact`?

- **`preset`** — статичний тижневий план відключень (7 днів × N груп × 48 слотів).
  Кожен слот: `"yes"` (є електрика) або `"no"` (відключення).

- **`fact`** — підтверджений графік НЕК Укренерго на сьогодні і завтра.
  Оновлюється протягом дня. Може містити `"maybe"`, `"first"`, `"second"` тощо.

### Захист WAF

Сайти DTEK захищені WAF Incapsula/Imperva. Клієнт обробляє це двома способами:

1. **Автоматичний прогрівний GET** — при `connect()` клієнт одноразово завантажує
   сторінку графіка, щоб отримати WAF-cookies перед POST-запитами.
2. **Модуль `browser_auth`** — для сайтів, де автоматичного прогріву недостатньо,
   використовуйте `get_cleared_cookies()` для запуску headless-браузера Playwright,
   який вирішує JS-challenge і повертає готові до використання cookies + CSRF-токен.

---

## 2. Перший запуск

### Передумови

| Інструмент | Версія | Встановлення |
|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) |
| Poetry | 1.8+ | `pip install poetry` |
| Git | будь-яка | [git-scm.com](https://git-scm.com) |
| Playwright (опційно) | остання | `poetry run playwright install chromium` |

### Налаштування

```bash
# 1. Клонувати репозиторій
git clone https://github.com/shed-crypto/dtek-blackout-client.git
cd dtek-blackout-client

# 2. Встановити всі залежності (включно з dev)
poetry install

# 3. (Опційно) встановити браузер Playwright для обходу WAF
poetry run playwright install chromium

# 4. Перевірити, що все працює
poetry run pytest
```

Очікуваний вивід:
```
174 passed in 6.41s
Total coverage: 99.83%
```

---

## 3. Структура проекту

```
dtek-blackout-client/
│
├── dtek_client/                   ← пакет, що встановлюється
│   ├── __init__.py                ← публічний API (те, що імпортується зовні)
│   ├── client.py                  ← DtekClient — основний асинхронний HTTP-клієнт
│   ├── models.py                  ← Pydantic v2 моделі для всіх відповідей
│   ├── exceptions.py              ← ієрархія винятків
│   ├── const.py                   ← URL всіх 6 сайтів DTEK, константи слотів,
│   │                                 REGION_NAMES / REGION_NAMES_EN / REGION_NAMES_UA
│   ├── stub_client.py             ← StubDtekClient (хардкодені дані, без мережі)
│   └── browser_auth.py            ← допоміжний модуль обходу WAF через Playwright
│
├── tests/
│   ├── conftest.py                ← спільні pytest-фікстури + make_mock_response()
│   ├── test_client.py             ← тести DtekClient (весь HTTP замокований через curl_cffi)
│   ├── test_models.py             ← тести Pydantic-моделей
│   ├── test_exceptions.py         ← тести ієрархії винятків
│   ├── test_stub_client.py        ← тести StubDtekClient
│   └── fixtures/
│       ├── home_num_response.json ← реалістична фікстура відповіді getHomeNum
│       └── streets_response.json  ← реалістична фікстура відповіді getStreets
│
├── .github/workflows/
│   ├── ci.yml                     ← lint + тести на кожен PR (Python 3.11 + 3.12)
│   └── publish.yml                ← збірка + PyPI при git-тезі
│
├── manual_test.py                 ← ручний інтеграційний тест (не комітити)
├── pyproject.toml                 ← конфігурація Poetry + mypy + ruff + black + pytest
├── README.md                      ← документація для користувачів
└── CONTRIBUTING.md                ← цей файл
```

### Ключові архітектурні рішення

- **`curl_cffi`** використовується замість `aiohttp`, бо може імітувати реальний
  браузер Chrome (`impersonate="chrome120"`), що необхідно для проходження
  TLS-перевірки на сайтах DTEK.
- Усі Pydantic-моделі — `frozen=True` — безпечно передавати між корутинами.
- `_handle_response()` — **синхронний** метод: `curl_cffi` відповіді надають
  `.json()` як звичайний метод, не корутину.
- `StubDtekClient` використовує `model_construct()` для обходу валідаторів моделей
  (які очікують сирі AJAX-словники), щоб будувати моделі з вже сконструйованих об'єктів.

---

## 4. Ручне тестування

`manual_test.py` у корені проекту демонструє повний WAF-bypass для
`krem` (Київська регіональна) та `oem` (Одеська). Запустіть локально:

```bash
poetry run python manual_test.py
```

> Якщо сайт DTEK тимчасово недоступний, замініть `DtekClient` на
> `StubDtekClient` в одному рядку імпорту — всі методи ідентичні.

Для мінімального ручного тесту без обходу WAF:

```python
import asyncio
from dtek_client import DtekClient

async def main() -> None:
    async with DtekClient("krem") as client:
        streets = await client.get_streets("м. Українка")
        for s in streets:
            print(s.name)

        response = await client.get_home_num("м. Українка", "вул. Юності")
        for house, entry in sorted(response.houses.items()):
            status = "excluded" if entry.is_excluded else entry.primary_group
            print(f"  {house:6s} → {status}")

asyncio.run(main())
```

---

## 5. Запуск автоматичних тестів

```bash
# Усі тести з покриттям:
poetry run pytest

# Один файл:
poetry run pytest tests/test_models.py -v

# Тести за ключовим словом:
poetry run pytest -k "TestGetGroupByAddress" -v

# Покриття як HTML (відкрити у браузері):
poetry run pytest --cov-report=html
open htmlcov/index.html
```

> Тести **ніколи не роблять реальних HTTP-запитів**. Всі виклики `_post()` та
> `_get_ajax_url()` замоковані через `unittest.mock.AsyncMock` та хелпер
> `make_mock_response()` з `conftest.py`. Тести проходять без Інтернету.

### Написання нових тестів

Використовуйте хелпер `make_mock_response()` з `conftest.py` для створення
сумісних з curl_cffi мок-відповідей:

```python
from tests.conftest import make_mock_response

resp = make_mock_response(status_code=200, json_data={"result": True, "data": {}})
# resp.status_code → 200
# resp.json()      → {"result": True, "data": {}}
# resp.headers     → {}
```

Увага: `_handle_response()` — **синхронний** метод — не `await`-те його в тестах.

---

## 6. Інструменти якості коду

```bash
# Ruff — лінтер (замінює flake8 + isort)
poetry run ruff check dtek_client/

# Black — перевірка форматування (без змін)
poetry run black --check dtek_client/ tests/

# Black — автоматичне виправлення форматування
poetry run black dtek_client/ tests/

# mypy — строга статична перевірка типів
poetry run mypy dtek_client/
```

Запустити все разом:

```bash
poetry run ruff check dtek_client/ && \
poetry run black --check dtek_client/ tests/ && \
poetry run mypy dtek_client/
```

---

## 7. Передача бібліотеки колегам (Стаб)

`StubDtekClient` — це замінник, що повертає хардкодені, але реалістичні
дані — без мережевих запитів і скрейпінгу сайтів.

Колезі потрібно змінити **один рядок імпорту**:

```python
# Під час розробки — використовуйте стаб:
from dtek_client.stub_client import StubDtekClient as DtekClient

# Коли реальний клієнт готовий — поверніть:
from dtek_client import DtekClient
```

Все інше залишається **ідентичним**.

Що повертає стаб:

| Метод | Дані |
|---|---|
| `get_streets("м. Українка")` | 4 вулиці |
| `get_home_num("м. Українка", "вул. Юності")` | 9 будинків з групами GPV3.1, GPV3.2, GPV4.1 |
| `get_group_by_address("м. Українка", "вул. Юності", "1/1")` | GPV3.2 |
| `get_today_schedule("м. Українка", "вул. Юності", "1")` | Слоти 1–8 та 37–44 = `NO` (відключення) |

---

## 8. Публікація на PyPI

### Одноразове налаштування

1. Зареєструйтесь на [pypi.org](https://pypi.org) та [test.pypi.org](https://test.pypi.org)
2. Перевірте, що ім'я `dtek-blackout-client` вільне

### Кроки ручної публікації

```bash
# 1. Оновіть версію у двох місцях:
#    pyproject.toml          → version = "0.1.1"
#    dtek_client/__init__.py → __version__ = "0.1.1"

# 2. Зберіть пакет:
poetry build
# створить:
#   dist/dtek_blackout_client-0.1.1.tar.gz
#   dist/dtek_blackout_client-0.1.1-py3-none-any.whl

# 3. Перевірте пакет:
pip install twine
twine check dist/*

# 4. Спочатку опублікуйте на TestPyPI (безпечно):
twine upload --repository testpypi dist/*
# Перевірте: https://test.pypi.org/project/dtek-blackout-client/
pip install --index-url https://test.pypi.org/simple/ dtek-blackout-client
python3 -c "from dtek_client import DtekClient; print('OK')"

# 5. Опублікуйте на PyPI:
twine upload dist/*
```

### Автоматична публікація через GitHub Actions

Просто створіть тег — все інше відбувається автоматично:

```bash
git add pyproject.toml dtek_client/__init__.py
git commit -m "chore: bump version to 0.1.1"
git tag v0.1.1
git push origin main --tags
```

`publish.yml` автоматично виконує: lint → test → build → TestPyPI → PyPI → GitHub Release.

---

## 9. Налаштування CI/CD на GitHub

### Крок 1 — завантажити код

```bash
git init
git add .
git commit -m "feat: initial release of dtek-blackout-client"
git branch -M main
git remote add origin https://github.com/shed-crypto/dtek-blackout-client.git
git push -u origin main
```

### Крок 2 — налаштувати Trusted Publishing на PyPI

На **pypi.org** → Account Settings → Publishing → Add publisher:
- Project name: `dtek-blackout-client`
- Owner: `shed-crypto`
- Repository: `dtek-blackout-client`
- Workflow: `publish.yml`
- Environment: `pypi`

Повторіть на **test.pypi.org** з environment `testpypi`.

### Крок 3 — GitHub Environments

GitHub → Settings → Environments → Create:
- `pypi`
- `testpypi`

### Крок 4 — Codecov (опційно)

1. Увійдіть на [codecov.io](https://codecov.io) через GitHub OAuth
2. Увімкніть репозиторій
3. Додайте `CODECOV_TOKEN` до GitHub Secrets

---

## 10. Типові помилки

### `DtekSiteError: Unknown site_key`
```python
# Неправильно:
client = DtekClient("kyiv")

# Правильно — використовуйте site_key з DTEK_SITES:
client = DtekClient("kem")   # DTEK Kyiv City Networks
client = DtekClient("krem")  # DTEK Kyiv Regional Networks
```

### `DtekConnectionError: Session not open`
```python
# Неправильно:
client = DtekClient("kem")
streets = await client.get_streets("м. Українка")  # ПОМИЛКА

# Правильно:
async with DtekClient("kem") as client:
    streets = await client.get_streets("м. Українка")
```

### `DtekNotFoundError: House '10' not found`
Номери будинків у базі DTEK можуть відрізнятися від поштових адрес.
Спочатку викличте `get_home_num()` і перегляньте `response.available_houses`.

### Incapsula WAF блокує запит
Сайт повернув сторінку з JS-challenge замість реального HTML. Два варіанти:

```python
# Варіант А: використати browser_auth для отримання cookies
from dtek_client.browser_auth import get_cleared_cookies
cookies, csrf_token = await get_cleared_cookies("https://www.dtek-krem.com.ua/ua/shutdowns")

# Варіант Б: відкрити сторінку в реальному браузері, скопіювати ajaxUrl з DevTools
# Network → XHR → знайти POST до /ua/ajax або /wp-admin/admin-ajax.php
client = DtekClient("krem", ajax_url="https://www.dtek-krem.com.ua/ua/ajax")
```

### `pydantic.ValidationError` у тестах
Перевірте, що фікстурний JSON відповідає реальній структурі відповіді сайту.
Запустіть `manual_test.py` і порівняйте.

### mypy скаржиться на типи
```bash
poetry run mypy dtek_client/ --show-error-codes
# Використовуйте type: ignore[...] лише як крайній захід — краще виправте тип
```

### Тести падають з `AttributeError: 'MagicMock' object has no attribute 'status_code'`
Клієнт тепер використовує `curl_cffi`, який надає `.status_code` (не `.status`).
Використовуйте `make_mock_response()` з `conftest.py` замість ручного створення моків.

---

## 11. Чекліст захисту проекту

### Репозиторій
- [ ] Репозиторій відкритий на GitHub
- [ ] Регулярні коміти з повідомленнями у стилі Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`)
- [ ] `README.md` з описом англійською, прикладами та таблицею регіонів
- [ ] `CONTRIBUTING.md` (цей файл) — Гайд розробника

### CI/CD — зелені бейджі
- [ ] `ci.yml` — зелений на GitHub ✅ (запускається на Python 3.11 + 3.12)
- [ ] Бейдж покриття > 90%
- [ ] `publish.yml` — налаштований з Trusted Publishing

### Якість коду
- [ ] `poetry run pytest` — всі тести проходять
- [ ] `poetry run pytest --cov` — покриття > 90%
- [ ] `poetry run ruff check dtek_client/` — без помилок
- [ ] `poetry run black --check dtek_client/ tests/` — без помилок
- [ ] `poetry run mypy dtek_client/` — без помилок

### PyPI
- [ ] `pip install dtek-blackout-client` — працює
- [ ] `from dtek_client import DtekClient` — імпортується коректно

### Командна інтеграція
- [ ] HA-інтеграція імпортує `StubDtekClient` і може відразу починати розробку
- [ ] `get_group_by_address()` повертає реальні дані з живого сайту
- [ ] Code review — залишені коментарі до PR

### Що демонструвати на захисті
1. GitHub → зелені CI-бейджі
2. `poetry run pytest` → 90%+ покриття в терміналі
3. `manual_test.py` → реальні дані з `dtek-krem.com.ua`
4. `pypi.org/project/dtek-blackout-client` → сторінка опублікованого пакету
5. Код колеги для HA → `from dtek_client import DtekClient` працює

---

## Участь у розробці

### Гілки

```bash
git checkout -b feat/add-check-update-method
```

### Стиль комітів (Conventional Commits)

```
feat: add checkDisconUpdate polling method
fix: handle empty streets list from getStreets
test: cover DtekSiteError on missing ajaxUrl meta
docs: update README with WAF bypass example
chore: bump curl-cffi to 0.14.1
```

### Процес Pull Request

1. Гілка від `main`
2. Написати тести для нового коду
3. `poetry run pytest` — зелений
4. Лінтери — без помилок
5. Відкрити PR до `main`

---

*Цей файл є Гайдом розробника (Етап 4 технічного завдання).
Всі коментарі у вихідному коді — англійською; українська з'являється лише у
рядкових значеннях (назви міст, мітки графіків), де це відображає реальний API DTEK.*