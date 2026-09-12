"""Load YAML test cases as pytest.param entries with markers from `tags:`.

Adopted directly from the reference framework's pattern: each YAML case
becomes a parametrized pytest case, and its `tags` become pytest markers
automatically -- so `--incl_tests=<tag>` / `--excl_tests=<tag>` filtering
works for every YAML-driven file with zero extra wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from utilities.logger import get_logger

logger = get_logger(__name__)

TESTCASES_DIR = Path(__file__).resolve().parent.parent / "testcases"


def load_cases(file_name: str) -> list:
    """Return a list of `pytest.param(case, marks=[...], id=case_id)` for
    `@pytest.mark.parametrize("case", load_cases("file.yaml"))`.

    Raises:
        FileNotFoundError: if `testcases/<file_name>` doesn't exist.
        ValueError: if the file isn't valid YAML, or a case entry is
            missing its required `id` key -- either would otherwise
            surface as a confusing collection-time error deep in pytest.
    """
    path = TESTCASES_DIR / file_name
    if not path.exists():
        raise FileNotFoundError(f"Test case file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse YAML in {path}: {exc}") from exc

    params = []
    for index, case in enumerate(raw.get("cases", [])):
        if "id" not in case:
            raise ValueError(f"Case at index {index} in {path} is missing required key 'id': {case!r}")
        case_id = case["id"]
        marks = [getattr(pytest.mark, t) for t in (case.get("tags") or [])]
        params.append(pytest.param(case, marks=marks, id=case_id))

    logger.debug("Loaded %d case(s) from %s", len(params), path)
    return params
