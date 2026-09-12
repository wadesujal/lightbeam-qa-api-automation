import logging
import re

# Matches "Bearer <token>" (and only the token part) so we can redact it from
# any log line without touching the rest of the message.
_BEARER_PATTERN = re.compile(r'(Bearer\s+)([^"\s]+)', re.IGNORECASE)


def mask_sensitive(text: str) -> str:
    """Never let a raw bearer token reach a log line."""
    if not text:
        return text
    return _BEARER_PATTERN.sub(lambda m: f"{m.group(1)}***MASKED***", text)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
