"""Per-test step recorder consumed by the HTML report plugin.

Adopted from the reference framework: a `with step_log.step("..."):` block
groups related assertions under a named step, and `step_log.record(...)`
(called by SoftAssert) attaches pass/fail detail to whichever step is
currently open -- so the HTML report can show a test as a sequence of
named, timed steps rather than one opaque pass/fail line.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Step:
    name: str
    status: str = "passed"
    details: list = field(default_factory=list)
    duration_ms: float = 0.0


class StepLog:
    def __init__(self):
        self.steps: list[Step] = []
        self._current: Step = None

    @contextmanager
    def step(self, name: str):
        step = Step(name=name)
        self.steps.append(step)
        previous = self._current
        self._current = step
        start = time.monotonic()
        try:
            yield step
        finally:
            step.duration_ms = (time.monotonic() - start) * 1000
            self._current = previous

    def record(self, detail: str, status: str) -> None:
        target = self._current or self._ensure_default_step()
        target.details.append(f"[{status}] {detail}")
        if status == "failed":
            target.status = "failed"

    def _ensure_default_step(self) -> Step:
        if not self.steps:
            self.steps.append(Step(name="assertions"))
        return self.steps[-1]
