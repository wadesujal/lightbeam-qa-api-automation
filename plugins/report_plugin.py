"""Pytest plugin: CLI tag filtering + Jinja2 HTML report with step detail.

Adopted from the reference framework's report plugin. Adds:
  --incl_tests=tag1,tag2     run only tests with at least one of these tags
  --excl_tests=tag1,tag2     skip tests carrying any of these tags
  --html-report=path         override the default report path
  --no-html-report           disable HTML report generation

Default: every run writes a fresh HTML report to
  reports/custom_report_<YYYYMMDD_HHMMSS>/report.html
and prints the absolute path at session end.

Tags come from pytest markers, so they compose naturally with the markers
`data_loader.load_cases()` attaches to each YAML-driven parametrized case.

Also installs a `step_log` fixture and stashes each test's StepLog onto the
pytest item so the report can render per-test steps without leaking state
between tests (or between xdist workers, if pytest-xdist is installed and
`-n auto` is used).
"""

from __future__ import annotations

import os
import platform
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from utilities.logger import get_logger
from utilities.steps import StepLog

logger = get_logger(__name__)

STEP_LOG_KEY = pytest.StashKey[StepLog]()
_REPORT_EXTRA_ATTR = "_api_report_extra"


# ── CLI options ─────────────────────────────────────────────────────────────


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the `--incl_tests`/`--excl_tests`/`--html-report`/
    `--no-html-report` CLI options under an `api-framework` group."""
    group = parser.getgroup("api-framework")
    group.addoption(
        "--incl_tests", action="store", default="",
        help="Comma-separated tags to include (run only tests with these markers).",
    )
    group.addoption(
        "--excl_tests", action="store", default="",
        help="Comma-separated tags to exclude (skip tests carrying these markers).",
    )
    group.addoption(
        "--html-report", action="store", default="",
        help="Override the HTML report path. Default: reports/custom_report_<ts>/report.html",
    )
    group.addoption(
        "--no-html-report", action="store_true", default=False,
        help="Skip HTML report generation entirely.",
    )


def _split(csv: str) -> set:
    """Split a comma-separated CLI option value into a set of trimmed,
    non-empty tags."""
    return {t.strip() for t in csv.split(",") if t.strip()}


# ── tag-based collection filter ─────────────────────────────────────────────


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    """Skip collected items that don't satisfy `--incl_tests`/`--excl_tests`,
    matched against each item's pytest markers."""
    incl = _split(config.getoption("--incl_tests"))
    excl = _split(config.getoption("--excl_tests"))
    if not incl and not excl:
        return

    skip_incl = pytest.mark.skip(reason=f"missing required tag (--incl_tests={','.join(sorted(incl))})")
    skip_excl = pytest.mark.skip(reason="tag excluded via --excl_tests")

    for item in items:
        item_tags = {m.name for m in item.iter_markers()}
        if incl and not (item_tags & incl):
            item.add_marker(skip_incl)
        if excl and (item_tags & excl):
            item.add_marker(skip_excl)


# ── fixture + per-item stash ────────────────────────────────────────────────


@pytest.fixture
def step_log(request: pytest.FixtureRequest) -> StepLog:
    """Provide a fresh `StepLog` for the current test and stash it on the
    pytest item so `pytest_runtest_makereport` can pull its steps back out
    once the test finishes -- xdist-safe since the stash lives on the item,
    not on shared plugin state."""
    log = StepLog()
    request.node.stash[STEP_LOG_KEY] = log
    return log


# ── result capture ──────────────────────────────────────────────────────────


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """After each test phase, attach the test's outcome, tags, and recorded
    steps to the pytest report object as `_api_report_extra`, so the HTML
    report can be built from report objects alone."""
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    if report.when != "call" and report.outcome != "skipped":
        return

    log = item.stash.get(STEP_LOG_KEY, None)
    steps = [
        {"name": s.name, "status": s.status, "details": s.details, "duration_ms": s.duration_ms}
        for s in (log.steps if log else [])
    ]
    tags = sorted({m.name for m in item.iter_markers()} - {"parametrize"})

    extra = {
        "nodeid": report.nodeid,
        "outcome": report.outcome,
        "duration_s": getattr(report, "duration", 0.0),
        "longrepr": str(report.longrepr) if report.failed else "",
        "steps": steps,
        "tags": tags,
    }
    setattr(report, _REPORT_EXTRA_ATTR, extra)


def pytest_configure(config: pytest.Config) -> None:
    """Initialize the per-session result accumulator and start timestamp."""
    config._api_results = []
    config._api_started_at = datetime.now(timezone.utc)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Collect each finished test's `_api_report_extra` into the running
    session-wide results list consumed at `pytest_sessionfinish`."""
    if report.when != "call" and report.outcome != "skipped":
        return
    extra = getattr(report, _REPORT_EXTRA_ATTR, None)
    if extra is None:
        return
    config = _current_config()
    if config is not None:
        config._api_results.append(extra)


_GLOBAL_CONFIG = None


def pytest_sessionstart(session: pytest.Session) -> None:
    """Stash the session's config in a module-level so `pytest_runtest_logreport`
    can reach it without threading it through every call site."""
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = session.config


def _current_config():
    """Return the config stashed by `pytest_sessionstart`, or None before
    a session has started (defensive; shouldn't happen in practice)."""
    return _GLOBAL_CONFIG


# ── HTML rendering ──────────────────────────────────────────────────────────


def _default_report_path() -> Path:
    """Build the default timestamped report path used when neither
    `--html-report` nor `--no-html-report` is passed."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("reports") / f"custom_report_{ts}" / "report.html"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Render and write the HTML report once the whole session is done.
    A failure to render/write the report is logged, not raised -- a broken
    report must never make an otherwise-good test run look like it failed."""
    if session.config.getoption("--no-html-report"):
        return

    override = session.config.getoption("--html-report")
    out = Path(override) if override else _default_report_path()

    results: list = list(getattr(session.config, "_api_results", []))
    if not results:
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        if tr is not None:
            for outcome, reports in tr.stats.items():
                if not isinstance(reports, list):
                    continue
                for r in reports:
                    if not isinstance(r, pytest.TestReport):
                        continue
                    results.append({
                        "nodeid": r.nodeid,
                        "outcome": r.outcome or outcome or "passed",
                        "duration_s": getattr(r, "duration", 0.0),
                        "longrepr": str(r.longrepr) if r.failed else "",
                        "steps": [],
                        "tags": [],
                    })

    totals = _summarise(results)
    started = getattr(session.config, "_api_started_at", datetime.now(timezone.utc))
    duration = (datetime.now(timezone.utc) - started).total_seconds()

    try:
        env = Environment(
            loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
            autoescape=select_autoescape(["html"]),
        )
        template = env.get_template("report.html.j2")
        html = template.render(
            env=os.environ.get("TEST_ENV", "qa"),
            host=socket.gethostname(),
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duration_s=f"{duration:.2f}",
            python_version=platform.python_version(),
            totals=totals,
            results=results,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    except Exception:
        logger.exception("Could not render/write the HTML report to %s -- test results are unaffected.", out)
        return

    abs_path = out.resolve()
    bar = "=" * 78
    sys.stdout.write(
        f"\n{bar}\n"
        f"  HTML REPORT  (passed={totals['passed']}, failed={totals['failed']}, "
        f"skipped={totals['skipped']}, total={totals['total']})\n"
        f"  file://{abs_path}\n  {abs_path}\n{bar}\n"
    )


def _summarise(results: list) -> dict:
    """Compute pass/fail/error/skipped counts and pass rate for the
    session's results, for the report header tiles."""
    total = len(results)
    passed = sum(1 for r in results if r["outcome"] == "passed")
    failed = sum(1 for r in results if r["outcome"] == "failed")
    error = sum(1 for r in results if r["outcome"] == "error")
    skipped = sum(1 for r in results if r["outcome"] == "skipped")
    pass_pct = round((passed / total) * 100, 1) if total else 0.0
    return {"total": total, "passed": passed, "failed": failed, "error": error, "skipped": skipped, "pass_pct": pass_pct}
