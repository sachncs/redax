"""Audit log backends.

The package exposes one Protocol (``Backend``) and concrete file and Redis
implementations.
"""

from .backend import Backend, Event, event_to_dict, pipeline_to_event, span_summary
from .file import FileAudit
from .redis import RedisAudit

__all__ = [
    "Backend",
    "Event",
    "FileAudit",
    "RedisAudit",
    "event_to_dict",
    "pipeline_to_event",
    "span_summary",
]
