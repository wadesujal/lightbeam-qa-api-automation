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

    # `raw.get("cases", [])` would return None for a file whose `cases:` key
    # is present but empty, so fall back with `or []` instead of a default.
    cases = raw.get("cases") or []
    if not isinstance(cases, list):
        raise ValueError(f"'cases' in {path} must be a list, got {type(cases).__name__}")

    params = []
    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or "id" not in case:
            raise ValueError(f"Case at index {index} in {path} is missing required key 'id': {case!r}")
        case_id = case["id"]
        # Duplicate ids produce indistinguishable pytest node ids ("case0", "case1"),
        # which makes a failure impossible to trace back to its YAML entry.
        if case_id in seen_ids:
            raise ValueError(f"Duplicate case id {case_id!r} in {path}")
        seen_ids.add(case_id)

        # `title` is mandatory: it is what a reader (or a reviewer looking at the
        # HTML report) actually sees, so a case without one would silently fall
        # back to a machine-generated name and the YAML would stop being the
        # single source of truth for what each scenario claims to prove.
        title = case.get("title")
        if not title or not str(title).strip():
            raise ValueError(
                f"Case {case_id!r} in {path} is missing a non-empty 'title'. "
                f"Add a one-line description of what the scenario validates."
            )

        marks = [getattr(pytest.mark, t) for t in (case.get("tags") or [])]
        # Carrying the title as a marker (rather than only inside the case dict)
        # lets the report plugin read it generically for YAML-driven and plain
        # pytest tests alike, without every test having to pass it along.
        marks.append(pytest.mark.title(str(title).strip()))
        params.append(pytest.param(case, marks=marks, id=case_id))

    logger.debug("Loaded %d case(s) from %s", len(params), path)
    return params
