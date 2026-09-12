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

TESTCASES_DIR = Path(__file__).resolve().parent.parent / "testcases"


def load_cases(file_name: str):
    """Return a list of pytest.param(case, marks=[...], id=case_id) for
    `@pytest.mark.parametrize("case", load_cases("file.yaml"))`."""
    path = TESTCASES_DIR / file_name
    if not path.exists():
        raise FileNotFoundError(f"Test case file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    params = []
    for case in raw.get("cases", []):
        case_id = case["id"]
        marks = [getattr(pytest.mark, t) for t in (case.get("tags") or [])]
        params.append(pytest.param(case, marks=marks, id=case_id))
    return params
