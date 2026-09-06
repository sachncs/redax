from __future__ import annotations

import pytest

from app.inference.detector import Span
from app.redaction.strategy import (
    Deid,
    Hash,
    Mask,
    Regex,
    Skip,
    Strategy,
)


def test_strategies_satisfy_protocol() -> None:
    for cls in (Skip(), Mask(), Hash(), Regex()):
        assert isinstance(cls, Strategy)


@pytest.mark.asyncio
async def test_pass_through_returns_unchanged() -> None:
    s = Skip()
    result = await s.apply("hello", [], {})
    assert result.text == "hello"
    assert result.spans == []
    assert result.relex_map == {}


@pytest.mark.asyncio
async def test_mask_substitutes_with_format() -> None:
    s = Mask()
    spans = [Span(0, 5, "PERSON", 1.0)]
    result = await s.apply("Alice!", spans, {"format": "<GONE>"})
    assert result.text == "<GONE>!"
    assert result.relex_map == {}


@pytest.mark.asyncio
async def test_hash_produces_deterministic_tokens() -> None:
    s = Hash(salt="pepper")
    spans = [Span(0, 5, "PERSON", 1.0)]
    result1 = await s.apply("Alice!", spans, {"length": 6})
    result2 = await s.apply("Alice!", [Span(0, 5, "PERSON", 1.0)], {"length": 6})
    assert result1.text == result2.text
    assert "[HASH:" in result1.text


@pytest.mark.asyncio
async def test_hash_different_salts_yield_different_tokens() -> None:
    spans = [Span(0, 5, "PERSON", 1.0)]
    a = await Hash(salt="salt-a").apply("Alice!", spans, {"length": 6})
    b = await Hash(salt="salt-b").apply("Alice!", spans, {"length": 6})
    assert a.text != b.text


@pytest.mark.asyncio
async def test_regex_strategy_runs_detector() -> None:
    s = Regex()
    result = await s.apply("Email a@b.com please", [], {"format": "<EMAIL>"})
    assert "<EMAIL>" in result.text


@pytest.mark.asyncio
async def test_auto_deid_emits_placeholders_when_relex_true() -> None:
    class _Stub:
        name = "stub"

        async def detect(self, text, entity_types):
            return [Span(0, 5, "PERSON", 0.9)]

        async def warmup(self):
            return None

    s = Deid(_Stub())
    result = await s.apply("Alice!", [], {"relex": True})
    assert "[PERSON_0000]" in result.text
    assert "Alice" in result.relex_map


@pytest.mark.asyncio
async def test_auto_deid_emits_format_when_relex_false() -> None:
    class _Stub:
        name = "stub"

        async def detect(self, text, entity_types):
            return [Span(0, 5, "PERSON", 0.9)]

        async def warmup(self):
            return None

    s = Deid(_Stub())
    result = await s.apply("Alice!", [], {"format": "<NAME>"})
    assert "<NAME>" in result.text
    assert result.relex_map == {}


@pytest.mark.asyncio
async def test_auto_deid_selects_policy_detector_by_name() -> None:
    class _Stub:
        name = "stub"

        async def detect(self, text, entity_types):
            return [Span(0, 5, "PERSON", 0.9)]

        async def warmup(self):
            return None

    class _Other(_Stub):
        name = "other"

    other = _Other()
    s = Deid(_Stub(), detectors={"stub": _Stub(), "other": other})
    result = await s.apply("Alice!", [], {"detector": "other", "relex": True})
    assert "[PERSON_0000]" in result.text


@pytest.mark.asyncio
async def test_auto_deid_rejects_unknown_policy_detector() -> None:
    class _Stub:
        name = "stub"

        async def detect(self, text, entity_types):
            return [Span(0, 5, "PERSON", 0.9)]

        async def warmup(self):
            return None

    s = Deid(_Stub(), detectors={"stub": _Stub()})
    with pytest.raises(ValueError, match=r"unknown detector 'nope'"):
        await s.apply("Alice!", [], {"detector": "nope"})


@pytest.mark.asyncio
async def test_auto_deid_rejects_multi_pass_above_cap() -> None:
    class _Stub:
        name = "stub"

        async def detect(self, text, entity_types):
            return [Span(0, 5, "PERSON", 0.9)]

        async def warmup(self):
            return None

    s = Deid(_Stub(), max_passes=3)
    with pytest.raises(ValueError, match=r"max_passes \(3\)"):
        await s.apply("Alice!", [], {"multi_pass": 9})
