from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given

from app.api.stream import split_chunks

_TEXT = st.text(st.characters(blacklist_categories=["Cs", "Cc"]), min_size=1, max_size=200)


@given(_TEXT, st.integers(min_value=1, max_value=64), st.integers(min_value=1, max_value=128))
def test_chunks_reassemble_the_source(text: str, chunk_chars: int, chunk_bytes: int) -> None:
    chunks = split_chunks(text, chunk_chars, chunk_bytes)
    assert "".join(chunks) == text
    assert chunks


@given(_TEXT, st.integers(min_value=1, max_value=64), st.integers(min_value=1, max_value=128))
def test_chunks_respect_char_and_byte_bounds(text: str, chunk_chars: int, chunk_bytes: int) -> None:
    for chunk in split_chunks(text, chunk_chars, chunk_bytes):
        assert len(chunk) <= chunk_chars
        if len(chunk.encode("utf-8")) > chunk_bytes:
            assert len(chunk) == 1


@given(_TEXT, st.integers(min_value=3, max_value=5), st.just(4))
def test_multibyte_text_is_split_without_splitting_characters(
    text: str, chunk_chars: int, chunk_bytes: int
) -> None:
    for chunk in split_chunks(text, chunk_chars, chunk_bytes):
        assert len(chunk.encode("utf-8")) <= chunk_bytes or len(chunk) == 1


def test_emoji_byte_budget_keeps_graphemes_whole() -> None:
    text = "😀😀😀😀😀😀"
    chunks = split_chunks(text, 100, 4)
    assert chunks == ["😀", "😀", "😀", "😀", "😀", "😀"]


def test_char_budget_takes_precedence_when_larger() -> None:
    text = "a" * 40
    chunks = split_chunks(text, 10, 10_000)
    assert [len(c) for c in chunks] == [10, 10, 10, 10]
