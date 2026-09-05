from __future__ import annotations

from app.inference.detector import Span
from app.redaction.relex import relexicalize


def test_replaces_with_typed_placeholders() -> None:
    spans = [Span(0, 5, "PERSON", 1.0)]
    out = relexicalize("Alice", spans)
    assert out.text == "[PERSON_0001]"
    assert out.relex_map == {"Alice": "[PERSON_0001]"}


def test_same_entity_same_placeholder_within_call() -> None:
    spans = [Span(0, 5, "PERSON", 1.0), Span(10, 15, "PERSON", 1.0)]
    out = relexicalize("Alice met Alice", spans)
    assert out.relex_map == {"Alice": "[PERSON_0001]"}
    assert out.text == "[PERSON_0001] met [PERSON_0001]"


def test_different_types_get_separate_counters() -> None:
    spans = [Span(0, 5, "PERSON", 1.0), Span(10, 15, "EMAIL", 1.0)]
    out = relexicalize("Alice a@b.com", spans)
    assert "[PERSON_0001]" in out.relex_map.values()
    assert "[EMAIL_0001]" in out.relex_map.values()


def test_same_type_distinct_entities_get_distinct_placeholders() -> None:
    spans = [Span(0, 5, "PERSON", 1.0), Span(10, 13, "PERSON", 1.0)]
    out = relexicalize("Alice Bob", spans)
    assert "[PERSON_0001]" in out.relex_map.values()
    assert "[PERSON_0002]" in out.relex_map.values()


def test_no_spans_returns_text() -> None:
    out = relexicalize("nothing", [])
    assert out.text == "nothing"
    assert out.relex_map == {}


def test_cross_request_cache_returns_same_placeholder() -> None:
    cache: dict[str, str] = {}
    out1 = relexicalize("Alice", [Span(0, 5, "PERSON", 1.0)], cross_request_cache=cache)
    out2 = relexicalize(
        "Alice",
        [Span(0, 5, "PERSON", 1.0)],
        seed=None,
        cross_request_cache=cache,
    )
    assert out1.relex_map == out2.relex_map


def test_seed_changes_placeholder_signature() -> None:
    spans = [Span(0, 5, "PERSON", 1.0)]
    a = relexicalize("Alice", spans, seed="alpha")
    b = relexicalize("Alice", spans, seed="beta")
    assert a.relex_map != b.relex_map


def test_seed_with_cross_request_cache_keeps_stability() -> None:
    cache: dict[str, str] = {}
    a = relexicalize("Alice", [Span(0, 5, "PERSON", 1.0)], seed="alpha", cross_request_cache=cache)
    b = relexicalize("Alice", [Span(0, 5, "PERSON", 1.0)], seed="alpha", cross_request_cache=cache)
    assert a.relex_map == b.relex_map
