import time
from dataclasses import dataclass
from typing import Any, Callable


class PollTimeoutError(TimeoutError):
    """Raised when wait_for_condition times out. Carries the last observed
    value and elapsed time so a failing test's message is actually useful."""


@dataclass
class PollResult:
    value: Any
    elapsed_seconds: float
    attempts: int


def wait_for_condition(
    poll_fn: Callable[[], Any],
    predicate: Callable[[Any], bool],
    timeout: float,
    interval: float,
    description: str = "condition",
) -> PollResult:
    """Poll poll_fn() until predicate(result) is truthy, or raise PollTimeoutError.

    This is the ONE reusable wait primitive for every asynchronous state
    transition in this framework (order status, export job status). It:
      - returns the instant the predicate is satisfied -- never over-waits
      - is always timeout-bound -- never an infinite loop
      - raises a diagnostic error (last value, elapsed time, attempt count)
        on timeout instead of a bare assertion failure

    Do not replace this with time.sleep(N) anywhere in the test suite.
    """
    start = time.monotonic()
    attempts = 0
    last_value = None

    while True:
        attempts += 1
        last_value = poll_fn()
        if predicate(last_value):
            return PollResult(value=last_value, elapsed_seconds=time.monotonic() - start, attempts=attempts)

        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            raise PollTimeoutError(
                f"Timed out after {elapsed:.1f}s waiting for {description}. "
                f"Last observed value: {last_value!r} (attempts: {attempts})"
            )
        time.sleep(min(interval, max(timeout - elapsed, 0)))
