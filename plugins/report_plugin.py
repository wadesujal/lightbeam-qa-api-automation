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
between tests.

Under `pytest -n auto` the report is written once, by the controller only,
from the terminal reporter's collected results -- per-step detail is a
serial-run feature, because the step data is built inside the worker
processes and pytest does not carry custom report attributes across the
worker/controller boundary. Run without `-n` when you want the stepped
report.
"""

from __future__ import annotations

import os
import platform
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from utilities.logger import get_logger
from utilities.steps import StepLog

logger = get_logger(__name__)

STEP_LOG_KEY = pytest.StashKey[StepLog]()
RESULTS_KEY = pytest.StashKey[list]()
STARTED_AT_KEY = pytest.StashKey[datetime]()
REPORT_PATH_KEY = pytest.StashKey[Path]()
_REPORT_EXTRA_ATTR = "_api_report_extra"

# Shared with xdist workers through the environment: they are separate
# processes that each run `pytest_configure`, so without this every worker
# would invent its own timestamped report directory.
_REPORT_DIR_ENV = "API_FRAMEWORK_REPORT_DIR"


# ── CLI options ─────────────────────────────────────────────────────────────


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the `--incl_tests`/`--excl_tests`/`--html-report`/
    `--no-html-report` CLI options under an `api-framework` group."""
    group = parser.getgroup("api-framework")
    group.addoption(
        "--incl_tests",
        action="store",
        default="",
        help="Comma-separated tags to include (run only tests with these markers).",
    )
    group.addoption(
        "--excl_tests",
        action="store",
        default="",
        help="Comma-separated tags to exclude (skip tests carrying these markers).",
    )
    group.addoption(
        "--html-report",
        action="store",
        default="",
        help="Override the HTML report path. Default: reports/custom_report_<ts>/report.html",
    )
    group.addoption(
        "--no-html-report",
        action="store_true",
        default=False,
        help="Skip HTML report generation entirely.",
    )


def _split(csv: str) -> set:
    """Split a comma-separated CLI option value into a set of trimmed,
    non-empty tags."""
    return {t.strip() for t in csv.split(",") if t.strip()}


# ── tag-based collection filter ─────────────────────────────────────────────


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    """Enforce the test-title convention, then skip collected items that don't
    satisfy `--incl_tests`/`--excl_tests`, matched against each item's markers."""
    _enforce_title_convention(items)

    incl = _split(config.getoption("--incl_tests"))
    excl = _split(config.getoption("--excl_tests"))
    if not incl and not excl:
        return

    skip_incl = pytest.mark.skip(
        reason=f"missing required tag (--incl_tests={','.join(sorted(incl))})"
    )
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


TITLE_PREFIX = "Validate that "


def _enforce_title_convention(items: list) -> None:
    """Fail collection if any test's report title doesn't start with
    `Validate that `.

    Same spirit as pytest's own `--strict-markers` (already on in
    `pyproject.toml`): a convention that isn't enforced quietly rots, and a
    report is only scannable if every row reads the same way. The failure names
    every offender at once so a reviewer fixes them in one pass, and it happens
    at collection -- before a single request is sent -- so it costs nothing.
    """
    offenders = [
        f"  {item.nodeid}\n    -> {_title_for(item)!r}"
        for item in items
        if not _title_for(item).startswith(TITLE_PREFIX)
    ]
    if offenders:
        raise pytest.UsageError(
            f"{len(offenders)} test(s) have a title that does not start with "
            f"{TITLE_PREFIX!r}.\n"
            + "\n".join(offenders)
            + "\n\nSet one with a YAML `title:` field (for testcases/*.yaml cases) or "
            '`@pytest.mark.title("Validate that ...")` (for direct pytest tests).'
        )


def _prettify(name: str) -> str:
    """Turn a pytest function name into a readable sentence as a last resort:
    `test_login_returns_token[empty_body]` -> `Login returns token [empty_body]`.
    Only used when a test carries neither a `title` marker nor a docstring."""
    base, sep, param = name.partition("[")
    words = base.removeprefix("test_").replace("_", " ").strip()
    title = words[:1].upper() + words[1:]
    return f"{title} [{param.rstrip(']')}]" if sep else title


def _title_for(item: pytest.Item) -> str:
    """Resolve the human-readable title shown in the HTML report.

    Resolution order, most explicit first:
      1. `@pytest.mark.title("...")` -- for YAML cases this marker is attached
         by `utilities/data_loader.py` from the case's `title:` field, so the
         report title and the YAML title are the same string by construction.
      2. The first line of the test's docstring.
      3. A prettified version of the test's own name.

    There is always a title, so a test can never show up in the report as a
    bare node id -- but only (1) and (2) are expected to satisfy the
    `Validate that ...` convention that `_enforce_title_convention` checks at
    collection time, so in practice an unlabelled test fails the run and gets
    a real title rather than shipping with a generated one.
    """
    marker = item.get_closest_marker("title")
    if marker and marker.args:
        return str(marker.args[0])

    doc = getattr(getattr(item, "obj", None), "__doc__", None)
    if doc and doc.strip():
        return doc.strip().splitlines()[0].strip()

    return _prettify(item.name)


def _is_reportable(report: pytest.TestReport) -> bool:
    """Should this phase report appear in the HTML report?

    The "call" phase of every test does. Non-"call" phases only do when they
    are not a plain pass, which is what keeps setup *errors* and setup-time
    skips in the report -- an earlier version dropped anything that wasn't a
    call or a skip, so a test that blew up in a fixture silently vanished
    from the report while pytest itself reported an error.
    """
    return report.when == "call" or report.outcome != "passed"


def _outcome_of(report: pytest.TestReport) -> str:
    """Classify a report the way pytest's own summary does: a failure outside
    the call phase is an *error* (broken fixture/teardown), not a test
    failure. Without this the report's "error" tile could never be non-zero."""
    if report.failed and report.when != "call":
        return "error"
    return report.outcome


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """After each test phase, record the test's outcome, tags, and steps into
    the session-wide results list held on `config.stash`.

    Collecting here (rather than in `pytest_runtest_logreport`) is deliberate:
    this hook receives the `item`, so it can reach both the item's stash and
    `item.config` directly, which removes the module-level global the previous
    implementation needed to find the config from a report-only hook."""
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    if not _is_reportable(report):
        return

    log = item.stash.get(STEP_LOG_KEY, None)
    steps = [
        {"name": s.name, "status": s.status, "details": s.details, "duration_ms": s.duration_ms}
        for s in (log.steps if log else [])
    ]
    # `title` is metadata for the report, not a filterable category, so it is
    # excluded from the tag chips the same way `parametrize` is.
    tags = sorted({m.name for m in item.iter_markers()} - {"parametrize", "title"})

    extra = {
        "nodeid": report.nodeid,
        "title": _title_for(item),
        "outcome": _outcome_of(report),
        "duration_s": getattr(report, "duration", 0.0),
        "longrepr": str(report.longrepr) if report.failed else "",
        "steps": steps,
        "tags": tags,
        # Captured log/stdout/stderr, attached only for tests that did not pass:
        # this is the request/response trace you need to triage a failure, and
        # embedding it for all 45 passing tests would bloat the report for no
        # gain -- the full DEBUG trace is in run.log either way. `sections` is a
        # standard TestReport field, so unlike `steps` it survives xdist
        # serialization and shows up in parallel runs too.
        "sections": (
            []
            if report.passed
            else [{"name": name, "content": content} for name, content in report.sections]
        ),
    }
    setattr(report, _REPORT_EXTRA_ATTR, extra)
    item.config.stash[RESULTS_KEY].append(extra)


def pytest_configure(config: pytest.Config) -> None:
    """Initialize the per-session result accumulator, start timestamp, report
    path, and per-run log file.

    The report directory is resolved once, here, instead of at session finish:
    the run's log file has to live beside the report it belongs to, and the
    timestamp should mark when the run started rather than when it ended.
    """
    config.stash[RESULTS_KEY] = []
    config.stash[STARTED_AT_KEY] = datetime.now(timezone.utc)

    report_path = _resolve_report_path(config)
    config.stash[REPORT_PATH_KEY] = report_path
    _configure_log_file(config, report_path.parent)


def _resolve_report_path(config: pytest.Config) -> Path:
    """Return this run's report path, stable across xdist worker processes."""
    override = config.getoption("--html-report")
    if override:
        return Path(override)

    shared_dir = os.environ.get(_REPORT_DIR_ENV)
    if shared_dir:
        return Path(shared_dir) / "report.html"

    path = _default_report_path()
    os.environ[_REPORT_DIR_ENV] = str(path.parent)
    return path


def _configure_log_file(config: pytest.Config, report_dir: Path) -> None:
    """Point pytest's `--log-file` at `<report dir>/run.log` unless the caller
    already chose a path.

    This is what turns "logs exist somewhere in the terminal scrollback" into
    "every run leaves a DEBUG-level trace of every HTTP call on disk", which is
    what you actually want when a test failed twenty minutes ago in CI. Runs
    before pytest's own logging plugin configures itself (that one is
    `trylast`), and each xdist worker gets its own file so parallel processes
    never interleave into one handle.
    """
    if config.getoption("log_file", None):
        return

    worker_id = getattr(config, "workerinput", {}).get("workerid")
    log_name = f"run-{worker_id}.log" if worker_id else "run.log"
    report_dir.mkdir(parents=True, exist_ok=True)
    config.option.log_file = str(report_dir / log_name)


# ── HTML rendering ──────────────────────────────────────────────────────────


def _results_from_terminal_reporter(config: pytest.Config) -> list:
    """Rebuild a summary-only result list from the terminal reporter's stats.

    Used only on the xdist controller. Filters with the same `_is_reportable`
    rule the main path uses: `tr.stats` also holds the passed setup/teardown
    phase reports under the "" key, and counting those would inflate the
    report's totals to roughly three entries per test."""
    tr = config.pluginmanager.get_plugin("terminalreporter")
    if tr is None:
        return []

    results = []
    for reports in tr.stats.values():
        if not isinstance(reports, list):
            continue
        for report in reports:
            if not isinstance(report, pytest.TestReport) or not _is_reportable(report):
                continue
            results.append(
                {
                    "nodeid": report.nodeid,
                    # The item (and therefore its title marker) lives in the worker
                    # process, so the controller falls back to the prettified name.
                    "title": _prettify(report.nodeid.rpartition("::")[2]),
                    "outcome": _outcome_of(report),
                    "duration_s": getattr(report, "duration", 0.0),
                    "longrepr": str(report.longrepr) if report.failed else "",
                    "steps": [],
                    "tags": [],
                    "sections": (
                        []
                        if report.passed
                        else [
                            {"name": name, "content": content} for name, content in report.sections
                        ]
                    ),
                }
            )
    return results


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

    # Under `pytest -n auto`, this hook runs in every xdist worker as well as
    # in the controller. Without this guard each worker writes its own
    # timestamped report directory, so a parallel run leaves N+1 reports on
    # disk and the only complete one is the controller's.
    if hasattr(session.config, "workerinput"):
        return

    out = session.config.stash.get(REPORT_PATH_KEY, None) or _default_report_path()

    results: list = list(session.config.stash.get(RESULTS_KEY, []))
    if not results:
        # xdist controller: the per-test extras were built inside the workers
        # and don't survive report serialization, so fall back to the
        # terminal reporter's collected reports (summary only, no step detail).
        results = _results_from_terminal_reporter(session.config)

    totals = _summarise(results)
    started = session.config.stash.get(STARTED_AT_KEY, datetime.now(timezone.utc))
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
        logger.exception(
            "Could not render/write the HTML report to %s -- test results are unaffected.", out
        )
        return

    abs_path = out.resolve()
    log_file = session.config.getoption("log_file", None)
    bar = "=" * 78
    banner = (
        f"\n{bar}\n"
        f"  HTML REPORT  (passed={totals['passed']}, failed={totals['failed']}, "
        f"error={totals['error']}, skipped={totals['skipped']}, total={totals['total']})\n"
        f"  file://{abs_path}\n  {abs_path}\n"
    )
    if log_file:
        banner += f"  run log: {Path(log_file).resolve()}\n"
    sys.stdout.write(banner + f"{bar}\n")


def _summarise(results: list) -> dict:
    """Compute pass/fail/error/skipped counts and pass rate for the
    session's results, for the report header tiles."""
    total = len(results)
    passed = sum(1 for r in results if r["outcome"] == "passed")
    failed = sum(1 for r in results if r["outcome"] == "failed")
    error = sum(1 for r in results if r["outcome"] == "error")
    skipped = sum(1 for r in results if r["outcome"] == "skipped")
    pass_pct = round((passed / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "error": error,
        "skipped": skipped,
        "pass_pct": pass_pct,
    }
