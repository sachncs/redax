from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

from app.inference.detector import Detector


class DetectorRegistry(Mapping[str, Detector]):
    """Name -> Detector lookup shared across strategies.

    Every detector the process owns (gliner2, regex) is registered once so
    the Regex strategy and AutoDeID fall back to the *same* instances -
    no duplicated rules, no divergent state.
    """

    def __init__(self, detectors: Iterable[Detector]) -> None:
        self._detectors: dict[str, Detector] = {d.name: d for d in detectors}

    def resolve(self, name: str) -> Detector:
        """Fetch a detector by name, failing loudly on unknown aliases."""
        try:
            return self._detectors[name]
        except KeyError:
            available = sorted(self._detectors)
            raise ValueError(
                f"unknown detector {name!r}; available detectors: {available}"
            ) from None

    def __getitem__(self, key: str) -> Detector:
        return self._detectors[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._detectors)

    def __len__(self) -> int:
        return len(self._detectors)

    def __repr__(self) -> str:
        return f"DetectorRegistry({sorted(self._detectors)!r})"
