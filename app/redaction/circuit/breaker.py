"""Tiny per-call circuit breaker used to shed load when a model detector
starts failing.

We deliberately do NOT depend on `pybreaker` so the redax deployment stays
single-file-pure. The state machine mirrors pybreaker's CLOSED / OPEN /
HALF_OPEN behaviour:

* CLOSED: calls pass through; consecutive failures counted.
* OPEN: calls short-circuit with `CircuitOpenError`. After `cooldown_s`
  the next call is allowed through as a probe (HALF_OPEN).
* HALF_OPEN: the probe either succeeds (back to CLOSED) or fails (back to
  OPEN with a fresh cooldown).

Only transient failures count. Application bugs (`ValueError`, etc.) do
not count and re-raise immediately.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar


class CircuitOpenError(RuntimeError):
    """Raised by the breaker when it is OPEN and no probe slot is free."""


T = TypeVar("T")


@dataclass(frozen=True)
class CircuitStats:
    state: str
    consecutive_failures: int
    opened_at: float | None
    probes_in_flight: int
    total_calls: int
    total_failures: int


class CircuitBreaker:
    """Per-process circuit breaker.

    `failure_threshold` is the number of *consecutive* transient failures
    before the breaker opens. `cooldown_s` is how long OPEN lasts before a
    probe is allowed. `transient_predicate` decides which exceptions count
    as failures (default: any `Exception`).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_s: float = 5.0,
        transient_predicate: Callable[[BaseException], bool] | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.transient_predicate = transient_predicate or (lambda exc: isinstance(exc, Exception))
        self.lock = threading.Lock()
        self.state = "closed"
        self.consecutive_failures = 0
        self.opened_at: float | None = None
        self.probe_in_flight = False
        self.total_calls = 0
        self.total_failures = 0

    def _allow_call(self) -> tuple[bool, bool]:
        """Decide whether a call should proceed.

        Returns ``(allow, is_probe)``. Caller holds the lock.
        """
        if self.state == "closed":
            return True, False
        if self.state == "open":
            assert self.opened_at is not None
            if (time.monotonic() - self.opened_at) >= self.cooldown_s:
                if self.probe_in_flight:
                    return False, False
                self.probe_in_flight = True
                return True, True
            return False, False
        return True, False

    def _on_success(self, was_probe: bool) -> None:
        if was_probe:
            self.probe_in_flight = False
        self.consecutive_failures = 0
        self.state = "closed"
        self.opened_at = None

    def _on_failure(self, was_probe: bool) -> None:
        if was_probe:
            self.probe_in_flight = False
        self.total_failures += 1
        self.consecutive_failures += 1
        if was_probe or self.consecutive_failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.monotonic()

    def call(self, fn: Callable[..., T], *args: object, **kwargs: object) -> T:
        with self.lock:
            allow, is_probe = self._allow_call()
            if not allow:
                raise CircuitOpenError(f"circuit '{self.name}' is open")
            self.total_calls += 1
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            with self.lock:
                if self.transient_predicate(exc):
                    self._on_failure(is_probe)
                raise
        else:
            with self.lock:
                self._on_success(is_probe)
            return result

    def stats(self) -> CircuitStats:
        with self.lock:
            return CircuitStats(
                state=self.state,
                consecutive_failures=self.consecutive_failures,
                opened_at=self.opened_at,
                probes_in_flight=self.probe_in_flight,
                total_calls=self.total_calls,
                total_failures=self.total_failures,
            )

    def force_open(self) -> None:
        """Test helper: force the breaker OPEN."""
        with self.lock:
            self.state = "open"
            self.opened_at = time.monotonic()

    def force_closed(self) -> None:
        """Test helper: reset the breaker to CLOSED."""
        with self.lock:
            self.state = "closed"
            self.consecutive_failures = 0
            self.opened_at = None
            self.probe_in_flight = False
