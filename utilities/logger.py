"""Shared logging setup used across the framework instead of ad-hoc
`print()` calls, so log level, format, and destination are controlled in
one place and every module logs under its own dotted name."""

import logging
import re

# Matches "Bearer <token>" so a raw bearer token never reaches a log line.
_BEARER_PATTERN = re.compile(r'(Bearer\s+)([^"\s]+)', re.IGNORECASE)


def mask_sensitive(text: str) -> str:
    """Return `text` with any `Bearer <token>` value replaced by a mask,
    so tokens never end up in logs. Falsy input (None, "") is returned
    unchanged."""
    if not text:
        return text
    return _BEARER_PATTERN.sub(lambda m: f"{m.group(1)}***MASKED***", text)


def get_logger(name: str) -> logging.Logger:
    """Return a configured `logging.Logger` for `name` (typically
    `__name__`). Idempotent: calling it again for the same name reuses the
    existing logger instead of stacking duplicate handlers."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
