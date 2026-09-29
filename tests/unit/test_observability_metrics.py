from __future__ import annotations

from app.observability.metrics import QUEUE_DEPTH, decrement_queue_depth, queue_depth


def test_queue_depth_returns_zero_when_empty() -> None:
    """A fresh gauge reads as 0.0."""
    QUEUE_DEPTH.set(0)
    assert queue_depth() == 0.0


def test_queue_depth_reflects_inc_and_dec() -> None:
    """After incrementing the gauge, queue_depth() returns the new value."""
    QUEUE_DEPTH.set(0)
    QUEUE_DEPTH.inc()
    QUEUE_DEPTH.inc()
    assert queue_depth() == 2.0
    QUEUE_DEPTH.dec()
    assert queue_depth() == 1.0
    QUEUE_DEPTH.set(0)


def test_queue_depth_decrement_is_clamped() -> None:
    QUEUE_DEPTH.set(0)
    decrement_queue_depth()
    assert queue_depth() == 0.0
