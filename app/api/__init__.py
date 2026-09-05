"""HTTP route modules.

Each module exposes a register(app) function so app/main.py wires them up
without import-time coupling. New routes are added in later milestones.
"""

from .health import register as register_health

__all__ = ["register_health"]
