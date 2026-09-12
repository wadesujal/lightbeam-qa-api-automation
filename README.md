# QA API Test Automation Framework — LightBeam Assignment

A production-style Python/pytest automation suite for the stateful, dependent, and long-running
asynchronous endpoints described in the assignment (auth, orders, and CSV exports) against the
provided Node/Express mock server.

**Verified**: this exact suite was run end-to-end against a live instance of the vendored mock
server — **35/35 tests passing** (30 fast tests in <1s, full suite including real async waits in ~113s).

## Stack

- **Python + pytest** (required by the assignment brief).
- **`requests`** for HTTP, chosen over `httpx` because this suite is entirely synchronous/serial
  (pytest runs tests one at a time by default) — `requests` is the most battle-tested, dependency-light
  option for that shape of workload. `httpx` would only earn its keep if the suite needed native
  async/concurrent requests, which it doesn't.
- `pytest-html` for a shareable HTML report; `python-dotenv` so `.env` can override configuration.

## Repository layout

```
qa-api-automation/
├── mock-server/          # Vendored copy of the assignment's Gist mock server (unmodified),
│                          # included so CI/anyone can run the suite without depending on an
│                          # external gist staying reachable. Source: see "Mock server" below.
├── config/config.py       # All environment-tunable settings (base URL, timeouts, poll intervals)
├── src/
│   ├── clients/           # BaseClient (session/auth/retry/logging) + Auth/Order/Export clients
│   ├── builders/          # Test data factories + independent totalAmount calculation
│   └── utils/             # polling.py (reusable async wait utility), logger.py, validators.py
├── tests/                 # test_auth.py, test_orders.py, test_exports.py, conftest.py
└── .github/workflows/ci.yml
```

## Mock server

Vendored from: https://gist.github.com/sharanya-lb/b429b6e807f95a8df8216c4343ff6766 (unmodified,
included here for reproducible CI runs). The assignment's own setup steps also work if you'd rather
run it from the original gist.

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- git

## Setup

```bash
# 1. Start the mock server
cd mock-server
npm install
node server.js
# leave this running in its own terminal — it listens on http://localhost:3000

# 2. In a new terminal, set up the Python environment
cd qa-api-automation
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. (optional) copy and adjust environment config
cp .env.example .env
```

## Running the tests

```bash
pytest                              # full suite (includes ~15-75s real async waits)
pytest -m smoke                     # fastest, highest-value checks only
pytest -m "not slow"                # everything except the real-time async-wait tests (~<1s)
pytest -m orders                    # just the /orders suite
pytest -m exports                   # just the /exports suite
pytest --html=reports/report.html --self-contained-html   # HTML report
```

## Confirmed server behavior that shapes this suite

The mock server's source was read directly (not guessed) and the suite is written against its
actual behavior, some of which differs from what a literal reading of the assignment brief implies.
Full detail in `TEST_PLAN.md`; the highlights:

- **Auth is presence-only.** Any non-empty `username`/`apiKey` logs in; the returned token's value
  is never validated by `checkAuth` — only the `Authorization: Bearer <anything>` shape is checked.
  So there is no such thing as an "invalid/expired token" 401 against this server — only a missing
  header or a non-`Bearer` scheme produces 401.
- **Field validation is presence-only, not range-checked.** E.g. negative `quantity`/`unitPrice` on
  an order is accepted and simply flows into `totalAmount` — it is not rejected with a 400.
- **`CANCELLED` is a real, sticky status.** Once cancelled, an order can never advance to
  `PROCESSING`/`COMPLETED`. Cancelling an already-cancelled order succeeds again (200), it does not 404/409.
- **The exported CSV is static/hardcoded**, not generated from the orders created during a test run.
  Assertions check its structure (header + rows, `Content-Type: text/csv`), not order-specific data.

## Required vs. optional next steps

**Required by the assignment — done:** every endpoint and documented behavior in the assignment
table is covered with positive and negative tests; async state transitions use a reusable polling
utility (no fixed `sleep()`); `totalAmount` is independently recomputed and compared, never trusted
from the response; a CI workflow runs the suite against the vendored server.

**Optional, production-hardening ideas not built here (out of scope for the assignment):**
- Contract/schema validation (e.g. `jsonschema`/`pydantic`) instead of manual field checks.
- Load/concurrency testing of the async endpoints.
- `pytest-randomly` in CI to continuously verify order-independence (verified manually here by
  re-running the suite; not automated on every run).
- Dockerizing the mock server for even more reproducible CI/local runs.
- Mutation testing to validate the test suite itself catches injected regressions.
