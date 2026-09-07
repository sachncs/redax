"""HTTP route modules.

Each module exposes a register(app) function so app/main.py wires them up
without import-time coupling.
"""

from .batch import register as register_batch
from .health import register as register_health
from .jobs import register as register_jobs
from .policies import register as register_policies
from .redact import register as register_redact
from .stream import register as register_stream

__all__ = [
    "register_batch",
    "register_health",
    "register_jobs",
    "register_policies",
    "register_redact",
    "register_stream",
]
