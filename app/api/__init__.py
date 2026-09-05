"""HTTP route modules.

Each module exposes a register(app) function so app/main.py wires them up
without import-time coupling. New routes are added in later milestones.
"""

from .health import register as register_health
from .redact import register as register_redact

__all__ = ["register_health", "register_redact"]
