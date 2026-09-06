"""Stage 2: model stage. Runs the chosen OpenMed-PII encoder (or any
`Detector` instance) over the text.

The stage exposes a synchronous `detector_sync` method so the circuit
breaker can wrap it from a threadpool without leaking asyncio.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.inference.detector import Span


class _SyncDetector(Protocol):
    name: str

    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]: ...


class _AsyncDetector(Protocol):
    name: str

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]: ...


@dataclass
class ModelStage:
    """A pluggable model-backed detector.

    The pipeline expects any object with a synchronous method that takes
    ``(text, entity_types)`` and returns ``list[Span]``. The
    `OpenMedPIIDetector` exposes `detect_sync` natively; the `RegexDetector`
    is async-only and is wrapped by `run_async` as a fallback.
    """

    detector: _SyncDetector | _AsyncDetector | Any

    def detector_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        sync_attr: Callable[..., Any] | None = getattr(self.detector, "detect_sync", None)
        if callable(sync_attr):
            return list(sync_attr(text, entity_types))
        detect_attr: Callable[..., Any] = self.detector.detect  # type: ignore[union-attr]
        return run_async(detect_attr(text, entity_types))


def run_async(coro: Any) -> list[Span]:
    """Run ``coro`` synchronously, off the event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return list(ex.submit(asyncio.run, coro).result())
        return list(loop.run_until_complete(coro))
    except RuntimeError:
        return list(asyncio.run(coro))
