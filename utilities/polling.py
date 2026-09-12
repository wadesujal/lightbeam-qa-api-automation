"""Reusable async-wait utility.

The reference framework's domain (wallet transfers) didn't need this --
its state changes were synchronous. This assignment is built around
long-running asynchronous state (order lifecycle, export jobs), so this
module is the one piece of core infrastructure added beyond the reference
layout. It is used by every test that waits on a state transition; no test
anywhere in this suite uses a fixed time.sleep().
"""

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

    - Returns the instant the predicate is satisfied -- never over-waits.
    - Always timeout-bound -- never an infinite loop.
    - Raises a diagnostic error (last value, elapsed time, attempts) on timeout.
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
