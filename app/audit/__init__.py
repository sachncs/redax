"""Audit log backends.

The package exposes one Protocol (AuditBackend) and one concrete
implementation (LocalFileAuditBackend). A second backend (e.g. Postgres,
OTLP) is added here when one actually ships.
"""

from .backend import AuditBackend, AuditEvent, event_to_dict
from .local_file import LocalFileAuditBackend

__all__ = ["AuditBackend", "AuditEvent", "LocalFileAuditBackend", "event_to_dict"]
