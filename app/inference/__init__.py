"""Inference backends for PII detection.

The package exposes one Protocol (Detector) and the concrete
implementations that satisfy it. New detectors are added here when a
second NER backend actually ships.
"""

from .detector import Detector, Span

__all__ = ["Detector", "Span"]
