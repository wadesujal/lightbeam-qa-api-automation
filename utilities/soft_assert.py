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
    step_log: "StepLog" = None  # type: ignore[name-defined]
    _failures: list = field(default_factory=list)

    def check(self, condition: bool, label: str) -> bool:
        if condition:
            if self.step_log:
                self.step_log.record(label, "passed")
        else:
            self._failures.append(label)
            if self.step_log:
                self.step_log.record(label, "failed")
        return condition

    def equals(self, actual, expected, label: str) -> bool:
        return self.check(
            actual == expected,
            f"{label}: expected {expected!r}, got {actual!r}",
        )

    def assert_all(self) -> None:
        if self._failures:
            joined = "\n  - ".join(self._failures)
            raise AssertionError(f"{len(self._failures)} soft assertion(s) failed:\n  - {joined}")
