"""Name -> Detector lookup shared across strategies."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

from app.inference.detector import Detector


class DetectorRegistry(Mapping[str, Detector]):
    """Name -> Detector lookup shared across strategies.

    Every detector the process owns (gliner2, regex) is registered once so
    the Regex strategy and AutoDeID fall back to the *same* instances -
    no duplicated rules, no divergent state.

    Attributes:
        detectors: The internal name -> detector mapping. Public because
            the class is itself a ``Mapping`` view over this dict.
    """

    def __init__(self, detectors: Iterable[Detector]) -> None:
        self.detectors: dict[str, Detector] = {d.name: d for d in detectors}

    def resolve(self, name: str) -> Detector:
        """Fetch a detector by name, failing loudly on unknown aliases.

        Args:
            name: The detector's ``Detector.name``.

        Returns:
            The registered ``Detector`` instance.

        Raises:
            ValueError: If no detector is registered under ``name``.
        """
        try:
            return self.detectors[name]
        except KeyError:
            available = sorted(self.detectors)
            raise ValueError(
                f"unknown detector {name!r}; available detectors: {available}"
            ) from None

    def __getitem__(self, key: str) -> Detector:
        return self.detectors[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.detectors)

    def __len__(self) -> int:
        return len(self.detectors)

    def __repr__(self) -> str:
        return f"DetectorRegistry({sorted(self.detectors)!r})"
