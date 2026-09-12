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
    """One named, timed section of a test, with the pass/fail detail
    recorded against it."""

    name: str
    status: str = "passed"
    details: list = field(default_factory=list)
    duration_ms: float = 0.0


class StepLog:
    """Ordered collection of `Step`s for a single test. Created fresh per
    test by the `step_log` fixture in `plugins/report_plugin.py`."""

    def __init__(self):
        self.steps: list[Step] = []
        self._current: Step = None

    @contextmanager
    def step(self, name: str):
        """Open a new named step for the duration of the `with` block,
        timing it and making it the target for any `record()` calls made
        inside (directly, or via `SoftAssert`)."""
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
        """Attach one `detail` line with `status` ("passed"/"failed") to
        the currently-open step, creating a default step if none is open
        yet. Marks the step "failed" if any detail recorded against it is."""
        target = self._current or self._ensure_default_step()
        target.details.append(f"[{status}] {detail}")
        if status == "failed":
            target.status = "failed"

    def _ensure_default_step(self) -> Step:
        """Return the last step, creating a generic "assertions" step first
        if `record()` is called with no step currently open."""
        if not self.steps:
            self.steps.append(Step(name="assertions"))
        return self.steps[-1]
