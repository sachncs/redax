"""Stage 2: model stage.

Runs the chosen OpenMed-PII encoder (or any ``Detector`` instance) over
the text. The stage exposes a synchronous ``detector_sync`` method so the
circuit breaker can wrap it from a threadpool without leaking asyncio.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.inference.detector import Detector, Span


@dataclass
class ModelStage:
    """A pluggable model-backed detector usable by the pipeline.

    Attributes:
        detector: Anything implementing ``detect_sync(text, entity_types)``
            or ``async detect(text, entity_types)``. The ``OpenMedPIIDetector``
            exposes ``detect_sync`` natively; the ``RegexDetector`` is
            async-only and is wrapped by ``run_async`` as a fallback.
    """

    detector: Detector

    def detector_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        """Synchronously invoke the wrapped detector and return its spans.

        Prefers the detector's ``detect_sync`` method; falls back to
        scheduling the async ``detect`` coroutine via ``run_async``.

        Args:
            text: The input text to redact.
            entity_types: Optional list of entity types to filter on.

        Returns:
            The detector's spans as a list.
        """
        sync_attr: Callable[..., Any] | None = getattr(self.detector, "detect_sync", None)
        if callable(sync_attr):
            return list(sync_attr(text, entity_types))
        detect_attr: Callable[..., Any] = self.detector.detect
        return run_async(detect_attr(text, entity_types))

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        """Async passthrough that runs the wrapped detector's async detect.

        Mirrors the Detector protocol so ``ModelStage`` can be used as
        a standalone detector. Sync detectors can still be wrapped by
        going through :meth:`detector_sync` on a worker thread.

        Args:
            text: The input text to redact.
            entity_types: Optional list of entity types to filter on.

        Returns:
            The detector's spans as a list.
        """
        detector_detect = getattr(self.detector, "detect", None)
        if detector_detect is None:
            return list(self.detector_sync(text, entity_types))
        return list(await detector_detect(text, entity_types))


def run_async(coro: Any) -> list[Span]:
    """Run ``coro`` synchronously, off the event loop.

    Uses ``asyncio.run`` when no event loop is running, otherwise schedules
    the coroutine on a single-thread executor and waits for the result.

    Args:
        coro: A coroutine returned from ``Detector.detect(...)``.

    Returns:
        The coroutine's result materialised as a list.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return list(ex.submit(asyncio.run, coro).result())
        return list(loop.run_until_complete(coro))
    except RuntimeError:
        return list(asyncio.run(coro))
