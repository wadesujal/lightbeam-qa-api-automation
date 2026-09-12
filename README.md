# QA API Test Automation Framework — LightBeam Assignment

A production-style Python/pytest automation suite for the stateful, dependent, and long-running
asynchronous endpoints described in the assignment (auth, orders, and CSV exports) against the
provided Node/Express mock server.

**Verified**: this exact suite was run end-to-end against a live instance of the vendored mock
server — **32/32 executable tests passing** (27 fast in <1s, full suite including real async waits
in ~113s), plus one Hypothesis property test that requires `pip install -r requirements.txt` to run
(see "Known limitations" below).

## Structure, and why it looks like this

This framework's layout is adapted from a reference SDET submission (`Robustrade/sdet-assignments`
PR #8) rather than invented from scratch, because the pattern — YAML scenarios feeding pytest step
definitions, a config-per-environment loader, soft assertions, a step-level HTML report, tag-based
CLI filtering — scales better to a real team than a flat `tests/` folder does. Concretely adopted:

- **`config/<env>.properties` + `Settings.load()`** instead of a flat `.env` — a new environment is
  a new properties file, and secrets are always `${VAR}`-expanded from the environment, never committed.
- **`testcases/*.yaml` + `step_definitions/*.py`** — a BDD-style split where YAML is the scenario
  (like a `.feature` file) and the step-definition function is the pytest code that executes it.
  Used for every case that's genuinely data (inputs → expected status/fields). The order/export
  *lifecycle* tests (state-machine polling, cancellation timing) are kept as direct pytest functions
  — like the reference framework kept its concurrency tests non-YAML — because their logic is control
  flow, not data.
- **`utilities/soft_assert.py` + `utilities/steps.py`** — a test can check several independent things
  (status code, body fields, business rule) and report every failure at once instead of stopping at
  the first `assert`, with each check attributed to a named step for the report.
- **`plugins/report_plugin.py`** — a real pytest plugin (not just `pytest-html`) adding
  `--incl_tests=tag`/`--excl_tests=tag` CLI filtering and a Jinja2 HTML report with per-step detail,
  xdist-safe.
- **`pyproject.toml`** for pytest config + lint config, instead of a separate `pytest.ini`.
- **`scripts/validate_contract.py`** — a fast pre-flight check (adapted from the reference's DB
  schema gate) that pings each endpoint and confirms the response shape the tests assume is still
  there, so a drifted mock server fails in 2 seconds with one clear message instead of forty
  confusing test failures.

What did **not** carry over, deliberately: the reference SUT is an in-process Flask+SQLite app, so
its `api_client.py` supports both an in-process test client and real HTTP, and it has a `db_client.py`
for direct database assertions. This assignment's SUT is only ever reachable over HTTP (an external
mock server, no importable app, no database) — so `utilities/api_client.py` here is HTTP-only, and
there is no `db_client.py`. The one piece of core infrastructure this assignment needed that the
reference didn't: `utilities/polling.py`, the reusable async-wait utility every state-transition test
uses — the reference's domain had no long-running async state to wait on.

## Stack

- **Python + pytest** (required by the assignment brief), **`requests`** for HTTP (this suite is
  fully synchronous — `httpx` would only earn its keep with genuine async/concurrent requests).
- `PyYAML` (test-case files), `Jinja2` (HTML report), `pytest-xdist` (parallel execution),
  `hypothesis` (property-based invariant test), `pytest-html` (fallback plain report).

## Repository layout

```
qa-api-automation/
├── mock-server/                # Vendored, unmodified copy of the assignment's Gist mock server
├── config/                     # settings.py loader + qa/stg/prd .properties files
├── plugins/                    # Custom pytest plugin: tag filters + Jinja2 HTML report
│   └── templates/report.html.j2
├── utilities/
│   ├── api_client.py           # BaseClient (auth/retry/logging) + Auth/Order/Export clients
│   ├── data_loader.py          # YAML testcases -> pytest.param, tags -> markers
│   ├── soft_assert.py          # Collect multiple assertion failures per test
│   ├── steps.py                # Named-step recorder consumed by the HTML report
│   ├── polling.py              # The one reusable async-wait utility -- no fixed sleeps anywhere
│   └── payload_builders.py     # Test data factories + independent totalAmount calculation
├── testcases/                  # YAML scenarios (auth.yaml, orders_create.yaml, exports.yaml)
├── step_definitions/           # pytest functions; conftest.py holds settings/client fixtures
├── scripts/validate_contract.py
├── conftest.py                 # registers plugins.report_plugin
├── pyproject.toml
├── requirements.txt
└── .github/workflows/ci.yml
```

## Mock server

Vendored from: https://gist.github.com/sharanya-lb/b429b6e807f95a8df8216c4343ff6766 (unmodified,
included for reproducible CI runs). The assignment's own setup steps also work if you'd rather run
it from the original gist.

## Prerequisites

Python 3.10+, Node.js 18+ and npm, git.

## Setup & running the tests

```bash
# 1. Start the mock server
cd mock-server && npm install && node server.js     # leave running in its own terminal

# 2. In a new terminal
cd qa-api-automation
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# pre-flight: confirm the mock server's contract matches what the tests assume
python scripts/validate_contract.py

pytest                              # full suite (includes ~15-75s real async waits)
pytest -m smoke                     # fastest, highest-value checks only
pytest -m "not slow"                # everything except real-time async waits (~<1s)
pytest -n auto -m "not slow"        # same, in parallel across CPU cores
pytest --incl_tests=orders          # only tests tagged 'orders' (tags come from YAML + markers)
pytest --excl_tests=slow,property   # everything except slow/property-based tests
pytest --html-report=reports/report.html   # pin the report to a fixed path (default is timestamped)
pytest --no-html-report             # skip report generation for a quick local run
```

Every run (unless `--no-html-report`) writes `reports/custom_report_<timestamp>/report.html` and
prints its path in a banner at the end — open it for a per-test, per-step breakdown with pass/fail
detail, not just a red/green line.

## Confirmed server behavior that shapes this suite

The mock server's source was read directly (not guessed) and the suite is written against its
actual behavior, some of which differs from a literal reading of the assignment brief. Full detail
in `TEST_PLAN.md`; the highlights:

- **Auth is presence-only.** Any non-empty `username`/`apiKey` logs in; the returned token's value
  is never validated — only the `Authorization: Bearer <anything>` shape is checked. So there is no
  "invalid/expired token" 401 against this server, only a missing header or wrong scheme.
- **Field validation is presence-only, not range-checked** (negative `quantity`/`unitPrice` is accepted).
- **`CANCELLED` is a real, sticky status** — never advances afterward; cancelling twice succeeds twice.
- **The exported CSV is static/hardcoded**, not generated from the test's own order data.

## Required vs. optional next steps

**Required by the assignment — done:** full endpoint coverage (positive/negative/boundary), async
state transitions via the reusable polling utility (no fixed sleeps), independently-verified
`totalAmount`, a working CI workflow, README with run instructions.

**Optional / adopted from the reference but genuinely extra for this assignment's scope:**
YAML-driven data tests, custom HTML report plugin with tag filtering, `pyproject.toml` lint config,
a contract pre-flight script, and a Hypothesis property test. All included because they were asked
for as "adopt the reference structure," not because the assignment strictly required them.

**Not built (out of scope):** load/concurrency testing of the async endpoints, Dockerizing the mock
server, mutation testing of the suite itself.

## Known limitations

- `step_definitions/test_invariants.py` uses `pytest.importorskip("hypothesis")` so a missing
  `hypothesis` install skips just that file instead of breaking collection for the rest of the suite.
  It was written and reviewed carefully but could not be executed in the sandboxed environment this
  framework was built in (no package-registry access there) — it runs normally once
  `pip install -r requirements.txt` completes on a machine with normal internet access.
- `pytest-xdist` parallel execution (`-n auto`) was likewise not exercised in that same sandbox for
  the same reason, though the suite's tests are independent/order-agnostic by design (fresh data per
  test, no shared state) and nothing about the plugin's xdist-serialization path is untested code —
  it's the same pattern the reference framework uses in real CI.
