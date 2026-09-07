"""Audit log backends.

The package exposes one Protocol (``Backend``) and one concrete
implementation (``FileAudit``). A second backend (e.g. Postgres, OTLP)
is added here when one actually ships.
"""

from .backend import Backend, Event, event_to_dict, pipeline_to_event, span_summary
from .file import FileAudit

__all__ = ["Backend", "Event", "FileAudit", "event_to_dict", "pipeline_to_event", "span_summary"]
