"""Pipeline stage modules.

Re-exports the public stage classes so callers can ``from
app.redaction.stages import Gate, ModelStage, fuse, from_regex_only``
without reaching into each submodule.
"""

from app.redaction.stages.consensus import fuse
from app.redaction.stages.fallback import from_regex_only
from app.redaction.stages.gate import Gate
from app.redaction.stages.model import ModelStage

__all__ = ["Gate", "ModelStage", "fuse", "from_regex_only"]
