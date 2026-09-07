from __future__ import annotations

import re

import hypothesis.strategies as st
from hypothesis import given

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


_TYPES = st.sampled_from(["PERSON", "EMAIL", "PHONE"])
_PLACEHOLDER = re.compile(r"\[[A-Z]+_\d{4}\]")
_SIGNED = re.compile(r"\[[A-Z]+_\d{4}\]-[0-9a-f]{4}")


@st.composite
def relex_case(draw):
    """Text segmented into entity tokens and plain parts.

    Token keys are unique per run and each carries a type stable within the
    run; spans cover exactly the entity token occurrences. Returns
    (text, spans, types).
    """
    token_choices = draw(st.lists(st.text("abcd", min_size=1, max_size=3), min_size=0, max_size=4))
    types = {f"e{i}:{tok}": draw(_TYPES) for i, tok in enumerate(token_choices)}
    kinds = draw(
        st.lists(
            st.one_of(st.just("other"), *[st.just(key) for key in types]),
            min_size=1,
            max_size=8,
        )
    )
    text_parts: list[str] = []
    spans: list[Span] = []
    pos = 0
    for kind in kinds:
        if kind == "other":
            value = draw(st.text("ab ", min_size=1, max_size=5))
        else:
            value = kind
            spans.append(Span(pos, pos + len(value), types[kind], 1.0))
        text_parts.append(value)
        pos += len(value)
    return "".join(text_parts), spans, types


@given(relex_case())
def test_relex_is_deterministic_without_cache(layout) -> None:
    text, spans, _ = layout
    a = relexicalize(text, spans)
    b = relexicalize(text, spans)
    assert a.text == b.text
    assert a.relex_map == b.relex_map


@given(relex_case())
def test_relex_placeholders_are_structured_and_unique(layout) -> None:
    text, spans, _ = layout
    out = relexicalize(text, spans)
    for entity, placeholder in out.relex_map.items():
        assert entity in text
        assert _PLACEHOLDER.fullmatch(placeholder), placeholder
    assert len(set(out.relex_map.values())) == len(out.relex_map.values())


@given(relex_case())
def test_relex_roundtrips_back_to_original(layout) -> None:
    text, spans, _ = layout
    if not spans:
        return
    out = relexicalize(text, spans)
    inverse = {placeholder: entity for entity, placeholder in out.relex_map.items()}
    restored = out.text
    for placeholder, entity in inverse.items():
        restored = restored.replace(placeholder, entity)
    assert restored == text


@given(relex_case(), st.text(min_size=1, max_size=4))
def test_relex_seed_produces_signed_placeholders_that_differ(layout, seed_alpha) -> None:
    text, spans, _ = layout
    if not spans:
        return
    with_repr = relexicalize(text, spans, seed="alpha")
    with_other = relexicalize(text, spans, seed="beta")
    assert _SIGNED.fullmatch(next(iter(with_repr.relex_map.values())))
    assert with_repr.text != with_other.text
