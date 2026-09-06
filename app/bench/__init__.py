"""RedactionBench benchmark harness for redax.

This package implements the R-Score metric, combinator structure (Algorithm 1),
prediction-dependent selection (Algorithm 2), and disagreement metrics from
Brynjolfsson et al. 2026 (arXiv:2606.18782).
"""

from app.bench.annotation import Annotation, LabelledSpan, SpanCategory, load_annotations
from app.bench.combinators import (
    ConnectorStructure,
    PairRange,
    SpanGroup,
    build_connector_structure,
)
from app.bench.corpus import (
    Category,
    Document,
    load_corpus,
)
from app.bench.disagreement import (
    DisagreementReport,
    pairwise_disagreement,
    per_unit_type_alpha,
    per_unit_type_disagreement,
    spearman_rank,
    wilson_interval,
)
from app.bench.fusion import (
    FusedEntities,
    fused_entity_groups,
    selected_contextual_spans,
)
from app.bench.rscore import (
    RDocument,
    RScoreReport,
    rscore,
    score_document,
)

__all__ = [
    "Annotation",
    "Category",
    "ConnectorStructure",
    "DisagreementReport",
    "Document",
    "FusedEntities",
    "LabelledSpan",
    "PairRange",
    "RDocument",
    "RScoreReport",
    "SpanCategory",
    "SpanGroup",
    "build_connector_structure",
    "fused_entity_groups",
    "load_annotations",
    "load_corpus",
    "pairwise_disagreement",
    "per_unit_type_alpha",
    "per_unit_type_disagreement",
    "rscore",
    "score_document",
    "selected_contextual_spans",
    "spearman_rank",
    "wilson_interval",
]
