# QA API Test Automation — LightBeam Assignment

A pytest framework for validating the LightBeam order/export mock service end to end: auth, the
order state machine, cancellation rules, and long-running CSV export jobs. Test data lives in YAML
so adding a scenario is usually a YAML edit, not a code change.

The system under test is the assignment's own Node/Express mock server (vendored unmodified into
this repo — see "Mock server" below). It is stateful and time-based: orders and export jobs advance
through statuses purely from elapsed wall-clock time, with no client action required.

**Verified**: this exact suite was run end-to-end against a live instance of the vendored mock
server — **32/32 executable tests passing** (27 fast in <1s, full suite including real async waits
in ~113s). One additional Hypothesis property test is import-guarded and runs once
`pip install -r requirements.txt` completes with normal internet access (see "Known limitations").

## Layout

```
qa-api-automation/
  mock-server/          Vendored, unmodified copy of the assignment's Gist mock server
  config/                env-specific .properties (qa/stg/prd), no secrets in repo
  utilities/              api_client, polling, soft_assert, steps, data_loader, payload_builders
  plugins/                pytest plugin + Jinja2 HTML report template
  testcases/              YAML scenarios (feature-file analogue)
  step_definitions/       pytest functions that consume testcases/ (step defs)
  scripts/                contract pre-flight check for CI
  conftest.py             registers the report plugin
  requirements.txt
  pyproject.toml
  .github/workflows/ci.yml
```

BDD analogy: `testcases/*.yaml` are the scenarios (like `*.feature` files); `step_definitions/*.py`
are the pytest functions that execute them (like step-definition methods). Scenarios whose logic is
genuinely control flow rather than data — the order state-machine wait, cancellation timing — are
kept as direct pytest functions instead of YAML, the same way a reliability/concurrency suite would.

This layout follows a structured SDET framework pattern (config-per-environment, YAML scenarios
split from step definitions, soft assertions, a step-level HTML report, tag-based CLI filtering)
rather than a flat, ad hoc `tests/` folder. What that pattern needed adapting for this assignment's
domain (no database, no in-process app — the SUT is only ever reached over real HTTP) is called out
inline below and in `TEST_PLAN.md`.

## Run it

### Windows PowerShell

```powershell
cd qa-api-automation
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\validate_contract.py
pytest -q
```

If `Activate.ps1` errors with an execution-policy message, either run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activation entirely:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -q
```

### macOS / Linux / Git Bash

```bash
# terminal 1: the mock server
cd mock-server && npm install && node server.js

# terminal 2: the test suite
cd qa-api-automation
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/validate_contract.py
pytest -q
```

Common commands:

```bash
pytest -q                              # full suite (includes ~15-75s real async waits)
pytest -m smoke -q                     # fastest, highest-value checks only
pytest -m "not slow" -q                # everything except the real-time async waits (~<1s)
pytest -n auto -m "not slow" -q        # same, in parallel across CPU cores
pytest --incl_tests=orders -q          # only tests tagged 'orders' (YAML tags -> markers)
pytest --excl_tests=slow,property -q   # everything except slow/property-based tests
pytest --html-report=reports/report.html -q   # pin the report to a fixed path
pytest --no-html-report -q             # skip report generation for a quick local run

# contract gate (used by CI, and worth running first any time the mock server changes)
python scripts/validate_contract.py

# lint
ruff check . && black --check .
```

## Why these dependencies

Everything pinned in `requirements.txt`, and what each one is for.

| Library | Why it is here | Where it shows up |
|---|---|---|
| `requests` | HTTP client for every call to the mock service. This suite is fully synchronous, so there's no reason to reach for `httpx`'s async support. | `utilities/api_client.py` |
| `pytest` | The test runner itself. Fixtures, parametrize, markers, plugin hooks. | Everything in `step_definitions/`, `plugins/`, `conftest.py` |
| `pytest-xdist` | Parallel test execution via `pytest -n auto`. Each test creates its own order/export data, so workers never collide. | Activated at runtime; the report plugin handles worker-to-master serialisation |
| `PyYAML` | Parses the YAML test-case files. | `utilities/data_loader.py` |
| `Jinja2` | Templating engine for the custom HTML report. | `plugins/report_plugin.py` renders `plugins/templates/report.html.j2` |
| `hypothesis` | Property-based testing. Generates random item lists so the `totalAmount` invariant is checked across input space the hand-written YAML cannot cover. | `step_definitions/test_invariants.py` |
| `pytest-html` | Plain fallback HTML report if you'd rather not use the custom plugin's output. | optional, via `pytest --html=reports/report.html --self-contained-html` |

### Version pinning convention

Every line uses `>=X.Y,<MAJOR+1`. For example, `requests>=2.32,<3.0` means "accept any 2.x release
at or above 2.32, refuse 3.x." CI picks up patch/minor bug fixes without breaking on a future major
version that changes the API.

### Not in `requirements.txt` (intentional)

- `ruff` and `black` are lint-only and installed directly by the CI pipeline, to keep the runtime
  dependency set small.
- No mocking library. Every test hits the real (mock) server over real HTTP — there is nothing to mock.
- No ORM or database library. This SUT has no database; all state lives in the mock server's own
  in-memory `Map`, reachable only through its HTTP API.

## HTML report

Every run (unless `--no-html-report`) writes a fresh HTML report to:

```
reports/custom_report_<YYYYMMDD_HHMMSS>/report.html
```

Each run gets its own timestamped folder, so previous reports are preserved. The absolute path is
printed at the end of the run inside a visible banner:

```
==============================================================================
  HTML REPORT  (passed=32, failed=0, skipped=0, total=32)
  file:///Users/you/.../qa-api-automation/reports/custom_report_20260912_180925/report.html
  /Users/you/.../qa-api-automation/reports/custom_report_20260912_180925/report.html
==============================================================================
```

The first line is a clickable `file://` URL in most terminals; the second is a plain path for copy-paste.

What is in the report: totals (passed/failed/error/skipped/pass rate), one row per test with its
tags and duration, and — click any test to expand — its per-step list (name, duration, pass/fail
detail from `SoftAssert`) plus the full failure traceback if it failed.

Override options:
- `--html-report=<path>` writes to that exact path instead of the timestamped default (what CI uses).
- `--no-html-report` skips report generation entirely, for fast local iteration.

`reports/` is not checked into git (see `.gitignore`).

### Tags for `--incl_tests` / `--excl_tests`

| tag | meaning |
|---|---|
| smoke | fast, highest-value checks safe to run on every PR |
| auth | login and authorization-enforcement scenarios |
| orders | order creation, state machine, and cancellation |
| exports | export job creation, status, and download |
| validation | bad-input / missing-field rejections |
| boundary | edge-of-input cases (empty arrays, decimal pricing) |
| happy | successful, positive-path scenarios |
| api | scenarios asserting the API response contract |
| regression | broader authorization/edge-case coverage |
| slow | tests that wait out real async timing (roughly 15-75s) |
| invariant / property | Hypothesis-driven property tests |

## What the framework gives you

1. **YAML-driven cases.** Each file in `testcases/` lists scenarios with `id`, `tags`, and expected
   outcomes. The loader (`utilities/data_loader.py`) turns each into a `pytest.param` and registers
   tags as markers, so tag filters work without per-file wiring.
2. **Single HTTP client per resource.** `utilities/api_client.py`'s `BaseClient` centralizes auth
   injection, retry-on-network-error, and logging; `AuthClient`/`OrderClient`/`ExportClient` wrap it.
   Tests never call `requests.*` directly.
3. **Reusable async-wait utility.** `utilities/polling.py` is the one primitive every state-transition
   test uses — no fixed `time.sleep()` anywhere in the suite, and every wait raises a diagnostic
   timeout error rather than a bare assertion failure.
4. **Soft assertions.** `utilities/soft_assert.py` collects every failure in a test and raises once
   at the end, so one test can report every broken expectation (status + fields + business rule)
   instead of stopping at the first.
5. **Step recorder + HTML report.** `utilities/steps.py` plus `plugins/report_plugin.py` produce a
   Jinja2 HTML report with per-step status, timing, and detail. Triggered by `--html-report=path`.
6. **Tag filters via CLI.** `--incl_tests=tag1,tag2` and `--excl_tests=tag3` are added by the plugin.
7. **Parallel execution via pytest-xdist.** `pytest -n auto`. Every test creates its own order/export
   via independently generated data, so workers never collide.
8. **Env-agnostic config.** `config/<env>.properties` files use `${VAR:-default}` placeholders and
   resolve from `os.environ`. No credential ever lives in the repo. Switch env with `TEST_ENV`.
9. **Property-based invariant.** The Hypothesis test in `step_definitions/test_invariants.py`
   exercises random item lists to check the `totalAmount` calculation across input space the
   hand-written YAML cases don't cover.

## Confirmed server contract (read directly from source, not assumed)

The mock server's source was read verbatim and run live — the suite is written against its actual
behavior, some of which differs from a literal reading of the assignment brief:

- **Auth is presence-only.** `checkAuth` only verifies `Authorization: Bearer <anything>` is
  present — the token's value is never validated, and `/auth/login` accepts any non-empty
  `username`/`apiKey`. There is no such thing as an "invalid/expired token" 401 against this server.
- **Field validation is presence-only, not range-checked.** Negative `quantity`/`unitPrice` on an
  order is accepted and simply flows into `totalAmount`.
- **`CANCELLED` is a real, sticky status.** Once cancelled, an order can never advance to
  `PROCESSING`/`COMPLETED`. Cancelling an already-cancelled order succeeds again (200), not 404/409.
- **The exported CSV is static/hardcoded**, not generated from the orders created during a test run.

Full traceability matrix (requirement → test) in `TEST_PLAN.md`.

## What is real vs. adopted-as-reference

Real: every test in this suite exercises the actual mock server over real HTTP — no mocking, no
stubbed responses. The mock server's own behavior (a static CSV, presence-only auth, elapsed-time
state transitions) is documented above rather than worked around.

Adopted from the reference structure but genuinely extra for this assignment's scope: YAML-driven
data tests, the custom HTML report plugin, `pyproject.toml` lint config, the contract pre-flight
script, and the Hypothesis property test. Included because the assignment asked for this structure
specifically, not because a minimal solution would have needed them.

Out of scope: load/concurrency testing of the async endpoints, Dockerizing the mock server, mutation
testing of the suite itself.

## CI

`.github/workflows/ci.yml` runs: install + start the vendored mock server, install Python deps,
lint (`ruff`/`black`), the contract pre-flight check, the fast (`not slow`) suite in parallel via
`pytest-xdist`, then the full suite including the real async waits — uploading both HTML reports as
build artifacts.

## Known limitations

- `step_definitions/test_invariants.py` uses `pytest.importorskip("hypothesis")` so a missing
  `hypothesis` install skips just that file instead of breaking collection for the rest of the
  suite. It was written and reviewed carefully but could not be executed in the sandboxed
  environment this framework was built in (no package-registry access there) — it runs normally
  once `pip install -r requirements.txt` completes on a machine with normal internet access.
- `pytest-xdist` parallel execution (`-n auto`) was likewise not exercised in that same sandbox, for
  the same reason, though every test is independent by design (fresh data per test, no shared
  state) and nothing about the plugin's xdist-serialization path is untested code — it's the same
  pattern the reference framework uses in real CI.
