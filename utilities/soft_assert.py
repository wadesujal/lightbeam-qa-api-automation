"""Collects every assertion failure in a test and raises them together at
the end, instead of stopping at the first `assert`. Adopted from the
reference framework: a single API-behavior test often checks several
independent things (status code, body fields, business rule) and a
reviewer benefits from seeing all of them fail at once rather than
re-running the test N times to find each broken expectation.
"""

from dataclasses import dataclass, field


@dataclass
class SoftAssert:
    """Accumulates named pass/fail checks for one test. Call `check()` or
    `equals()` any number of times, then `assert_all()` once at the end so
    every failure -- not just the first -- is reported together. When a
    `step_log` (see `utilities.steps.StepLog`) is supplied, each check is
    also recorded against the currently-open step for the HTML report."""

    step_log: "StepLog" = None  # type: ignore[name-defined]
    _failures: list = field(default_factory=list)

    def check(self, condition: bool, label: str) -> bool:
        """Record `condition` under `label`, without raising immediately.
        Returns `condition` unchanged so it can be used inline if needed."""
        if condition:
            if self.step_log:
                self.step_log.record(label, "passed")
        else:
            self._failures.append(label)
            if self.step_log:
                self.step_log.record(label, "failed")
        return condition

    def equals(self, actual, expected, label: str) -> bool:
        """Convenience wrapper around `check()` for an equality comparison;
        the recorded label includes both the expected and actual values."""
        return self.check(
            actual == expected,
            f"{label}: expected {expected!r}, got {actual!r}",
        )

    def assert_all(self) -> None:
        """Raise `AssertionError` listing every failed check recorded so
        far, if any. Call this once, at the end of the test."""
        if self._failures:
            joined = "\n  - ".join(self._failures)
            raise AssertionError(f"{len(self._failures)} soft assertion(s) failed:\n  - {joined}")
