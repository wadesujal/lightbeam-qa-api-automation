"""Shared logging setup used across the framework instead of ad-hoc `print()`
calls, so format and destination are controlled in one place and every module
logs under its own dotted name.

Loggers returned here deliberately install **no handler of their own** and do
**not** disable propagation: records travel up to the root logger, which is
where pytest's logging plugin attaches its capture handler. That is what makes
the "Captured log" section on a failing test, the `caplog` fixture, the
per-run `run.log`, and the log block in the HTML report work at all.

An earlier version attached a StreamHandler and set `propagate = False`, which
meant pytest never saw a single record: log lines survived only incidentally,
as captured stderr in the terminal, and were absent from the HTML report and
from any log file entirely.

Entry points that run outside pytest (`scripts/validate_contract.py`) call
`configure_stream_logging()` once to get console output.
"""

import logging
import re
import sys

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Matches "Bearer <token>" so a raw bearer token never reaches a log line.
_BEARER_PATTERN = re.compile(r'(Bearer\s+)([^"\s]+)', re.IGNORECASE)

_HANDLER_FLAG = "_api_framework_stream_handler"


def mask_sensitive(text: str) -> str:
    """Return `text` with any `Bearer <token>` value replaced by a mask,
    so tokens never end up in logs. Falsy input (None, "") is returned
    unchanged."""
    if not text:
        return text
    return _BEARER_PATTERN.sub(lambda m: f"{m.group(1)}***MASKED***", text)


def truncate(text: str, limit: int = 500) -> str:
    """Shorten `text` for a log line, marking that it was cut. Response bodies
    are logged on failure, and an unbounded body would bury the log."""
    if text is None:
        return ""
    text = str(text)
    return text if len(text) <= limit else f"{text[:limit]}... [{len(text) - limit} more chars]"


def get_logger(name: str) -> logging.Logger:
    """Return the `logging.Logger` for `name` (typically `__name__`).

    No handler is attached and propagation is left on, so whoever owns the
    process -- pytest, or `configure_stream_logging()` for a standalone
    script -- decides where records go.
    """
    return logging.getLogger(name)


def configure_stream_logging(level: int = logging.INFO) -> None:
    """Attach a stderr handler to the root logger for use outside pytest.

    Idempotent: calling it twice will not stack duplicate handlers, so a
    script that imports another script's module can't double-log.
    """
    root = logging.getLogger()
    if not any(getattr(handler, _HANDLER_FLAG, False) for handler in root.handlers):
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        setattr(handler, _HANDLER_FLAG, True)
        root.addHandler(handler)
    root.setLevel(level)
