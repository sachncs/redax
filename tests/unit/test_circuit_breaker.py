from __future__ import annotations

import pytest

from app.redaction.circuit.breaker import CircuitBreaker, CircuitOpenError


def test_closed_breaker_passes_calls() -> None:
    cb = CircuitBreaker(name="t", failure_threshold=2, cooldown_s=0.1)

    def add(a: int, b: int) -> int:
        return a + b

    assert cb.call(add, 2, 3) == 5
    assert cb.stats().state == "closed"
    assert cb.stats().total_calls == 1


def test_breaker_opens_after_repeated_failures() -> None:
    cb = CircuitBreaker(name="t", failure_threshold=2, cooldown_s=0.1)

    def boom() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        cb.call(boom)
    with pytest.raises(RuntimeError):
        cb.call(boom)
    assert cb.stats().state == "open"
    with pytest.raises(CircuitOpenError):
        cb.call(boom)


def test_breaker_half_opens_after_cooldown_and_recovers_on_success() -> None:
    cb = CircuitBreaker(name="t", failure_threshold=1, cooldown_s=0.05)

    def boom() -> None:
        raise RuntimeError("nope")

    def ok() -> str:
        return "ok"

    with pytest.raises(RuntimeError):
        cb.call(boom)
    assert cb.stats().state == "open"
    import time

    time.sleep(0.06)
    assert cb.call(ok) == "ok"
    assert cb.stats().state == "closed"


def test_breaker_half_open_failure_reopens() -> None:
    cb = CircuitBreaker(name="t", failure_threshold=1, cooldown_s=0.05)

    def boom() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        cb.call(boom)
    import time

    time.sleep(0.06)
    with pytest.raises(RuntimeError):
        cb.call(boom)
    assert cb.stats().state == "open"


def test_breaker_non_transient_does_not_count() -> None:
    cb = CircuitBreaker(
        name="t",
        failure_threshold=1,
        cooldown_s=0.1,
        transient_predicate=lambda exc: isinstance(exc, ConnectionError),
    )

    def boom() -> None:
        raise ValueError("programmer error")

    with pytest.raises(ValueError):
        cb.call(boom)
    assert cb.stats().state == "closed"


def test_force_open_and_force_closed() -> None:
    cb = CircuitBreaker(name="t", failure_threshold=1, cooldown_s=10.0)
    cb.force_open()
    assert cb.stats().state == "open"
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: 1)
    cb.force_closed()
    assert cb.stats().state == "closed"
    assert cb.call(lambda: 42) == 42
