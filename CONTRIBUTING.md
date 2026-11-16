# Contributing to dtek-blackout-client

Developer guide covering environment setup, architecture, testing, and release workflow.

---

## 1. Architecture Overview

DTEK regional sites (`kem`, `krem`, `dnem`, `dem`, `oem`) are Yii2 web applications that expose their schedule data through `POST /ua/ajax` protected by Yii2 CSRF validation:

1. **CSRF Bootstrap**: A `POST` to `/ua/ajax` without a token returns HTTP 400 and sets a signed `_csrf-dtek-<site>` cookie containing the 32-byte raw token.
2. **Token Masking**: `DtekClient` extracts the raw token and sends `X-CSRF-Token` masked via `base64url(mask + (mask XOR token))`.
3. **AJAX Methods**:
   - `method=getStreets` returns the settlement-to-streets mapping (or a flat street list on `kem`).
   - `method=getHomeNum` returns building entries, group assignments, static weekly plans (`preset`), and confirmed daily schedules (`fact`).

---

## 2. Development Setup

### Prerequisites
- Python 3.11+
- Poetry 1.8+
- Git

### Installation

```bash
git clone https://github.com/shed-crypto/dtek-blackout-client.git
cd dtek-blackout-client
poetry install
```

Optional Playwright browser setup (only needed if testing real browser WAF harvesting):

```bash
poetry run playwright install chromium
```

---

## 3. Project Structure

```text
dtek-blackout-client/
├── dtek_client/
│   ├── __init__.py       # Public package exports
│   ├── client.py         # DtekClient (aiohttp + Yii2 CSRF handling)
│   ├── models.py         # Frozen Pydantic v2 models and house normalization
│   ├── exceptions.py     # Exception hierarchy
│   ├── const.py          # Site registry (5 DTEK DSOs), constants, region names
│   ├── stub_client.py    # Offline drop-in StubDtekClient
│   └── browser_auth.py   # Optional Playwright cookie helper
├── tests/
│   ├── conftest.py       # Shared fixtures and mock aiohttp response helpers
│   ├── test_client.py    # Behavioral unit tests for DtekClient
│   ├── test_models.py    # Model parsing and DST schedule tests
│   ├── test_exceptions.py
│   ├── test_stub_client.py
│   ├── test_browser_auth.py
│   └── fixtures/
└── manual_test.py        # Manual verification script
```

---

## 4. Verification & Pre-Commit Standards

Before committing any change, run the full verification suite:

```bash
poetry run mypy dtek_client/
poetry run ruff check dtek_client/ tests/
poetry run black --check dtek_client/ tests/
poetry run pytest
```

### Engineering Standards
- All source code, comments, docstrings, commit messages, and documentation must be written in English.
- Do not use emojis in code, logs, or commit messages.
- Follow Conventional Commits (`feat`, `fix`, `refactor`, `test`, `build`, `ci`, `docs`, `style`, `chore`) with imperative subject lines under 72 characters.
- Maintain at least 90% test coverage with behavior-driven assertions.
