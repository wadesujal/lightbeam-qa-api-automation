"""Loads `config/<env>.properties`, expanding `${VAR}` and `${VAR:-default}`
tokens from os.environ. Switch envs with `TEST_ENV=stg` (or qa, prd).

Uses a per-environment properties file plus env-var expansion (no secrets
ever committed) rather than a flat .env file, so a new environment is a
new properties file, not a code change.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: str) -> str:
    """Replace every `${VAR}` / `${VAR:-default}` token in `value` with the
    matching environment variable, or the inline default if the variable
    is unset. Returns the string unchanged if it contains no tokens."""

    def repl(match: re.Match) -> str:
        name = match.group(1)
        default = match.group(2) or ""
        return os.environ.get(name, default)

    return _ENV_VAR_PATTERN.sub(repl, value).strip()


def _parse_properties(path: Path) -> dict:
    """Parse a `key=value` properties file into a dict, expanding env-var
    tokens in each value. Blank lines and lines starting with '#' are
    skipped; a line with no '=' is logged and skipped rather than raising,
    since a stray line in a properties file shouldn't fail the whole run.
    """
    props: dict = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not read properties file '{path}': {exc}") from exc

    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            logger.warning("Ignoring malformed line %d in %s: %r", line_number, path, raw)
            continue
        key, _, value = line.partition("=")
        props[key.strip()] = _expand(value)
    return props


@dataclass(frozen=True)
class Settings:
    """Immutable, environment-resolved configuration for every client and
    test in this framework. Never constructed directly -- always via
    `Settings.load()`, which is what actually knows how to find and parse
    the right `.properties` file."""

    env: str
    base_url: str
    request_timeout_seconds: int
    order_poll_interval_seconds: float
    order_poll_timeout_seconds: float
    export_poll_interval_seconds: float
    export_poll_timeout_seconds: float
    cancelled_observation_seconds: float

    @classmethod
    def load(cls, env: str = None) -> "Settings":
        """Load settings for `env` (default: `$TEST_ENV`, then "qa").

        Raises:
            FileNotFoundError: if no `config/<env>.properties` file exists
                for the resolved environment name.
            ValueError: if a numeric setting (timeout/poll interval) in the
                properties file can't be parsed as int/float.
        """
        env = (env or os.environ.get("TEST_ENV") or "qa").lower()
        root = Path(__file__).resolve().parent
        path = root / f"{env}.properties"
        if not path.exists():
            available = ", ".join(sorted(p.stem for p in root.glob("*.properties")))
            raise FileNotFoundError(f"Unknown TEST_ENV='{env}'. Expected one of: {available}")

        props = _parse_properties(path)

        def _get_float(key: str, default: str) -> float:
            raw_value = props.get(key, default)
            try:
                return float(raw_value)
            except ValueError as exc:
                raise ValueError(
                    f"Setting '{key}' in {path} must be numeric, got {raw_value!r}"
                ) from exc

        def _get_int(key: str, default: str) -> int:
            raw_value = props.get(key, default)
            try:
                return int(raw_value)
            except ValueError as exc:
                raise ValueError(
                    f"Setting '{key}' in {path} must be an integer, got {raw_value!r}"
                ) from exc

        settings = cls(
            env=props.get("env", env),
            base_url=props.get("base_url", ""),
            request_timeout_seconds=_get_int("request_timeout_seconds", "10"),
            order_poll_interval_seconds=_get_float("order_poll_interval_seconds", "1"),
            order_poll_timeout_seconds=_get_float("order_poll_timeout_seconds", "25"),
            export_poll_interval_seconds=_get_float("export_poll_interval_seconds", "2"),
            export_poll_timeout_seconds=_get_float("export_poll_timeout_seconds", "75"),
            cancelled_observation_seconds=_get_float("cancelled_observation_seconds", "18"),
        )
        logger.debug("Loaded settings for env=%s from %s", settings.env, path)
        return settings
