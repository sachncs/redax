"""High-level redaction: detector pipeline, policy loader, strategies.

The package is the public surface of the redaction engine. Public
classes (``Redactor``, ``RedactionResult``, ``Pipeline``, ``PipelineResult``,
``Outcome``, ``Gate``, ``ModelStage``, ``Breaker``, ``Policy``) and
helpers (``load_policy``, ``parse_policy``, ``parse_policy_dict``,
``list_policies``, ``fuse``, ``from_regex_only``) are re-exported here so
callers can ``from app.redaction import Redactor, load_policy`` without
reaching into individual submodules.
"""

from app.redaction.circuit.breaker import Breaker, OpenError
from app.redaction.pipeline import Outcome, Pipeline, PipelineResult
from app.redaction.policies import (
    Policy,
    list_policies,
    load_policy,
    parse_policy,
    parse_policy_dict,
)
from app.redaction.redactor import RedactionResult, Redactor
from app.redaction.stages import Gate, ModelStage
from app.redaction.stages.consensus import fuse
from app.redaction.stages.fallback import from_regex_only

__all__ = [
    "Breaker",
    "Gate",
    "ModelStage",
    "OpenError",
    "Outcome",
    "Pipeline",
    "PipelineResult",
    "Policy",
    "RedactionResult",
    "Redactor",
    "fuse",
    "from_regex_only",
    "list_policies",
    "load_policy",
    "parse_policy",
    "parse_policy_dict",
]
