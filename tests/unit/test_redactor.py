from __future__ import annotations

import pytest

from app.inference.detector import Span
from app.redaction.redactor import Redactor
from app.redaction.strategy import AutoDeID, Mask, PassThrough


class _StubDetector:
    name = "stub"

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        return [Span(0, 5, "PERSON", 0.9)] if text == "Alice!" else []

    async def warmup(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redact_with_no_policy_uses_plain_path() -> None:
    r = Redactor(detector=_StubDetector(), strategies={"mask": Mask()})
    out = await r.redact("Alice!")
    assert out.text == "[REDACTED]!"


@pytest.mark.asyncio
async def test_redact_with_policy_runs_strategies_in_order() -> None:
    r = Redactor(
        detector=_StubDetector(),
        strategies={
            "passThrough": PassThrough(),
            "autoDeID": AutoDeID(_StubDetector()),
        },
    )
    policy = {
        "fields": {
            "gender": {"strategy": "passThrough"},
            "name": {"strategy": "autoDeID", "relex": True},
        }
    }
    out = await r.redact("Alice!", policy=policy)
    assert out.text == "[PERSON_0000]!"


@pytest.mark.asyncio
async def test_redact_with_policy_unknown_strategy_is_skipped() -> None:
    r = Redactor(detector=_StubDetector(), strategies={"mask": Mask()})
    policy = {"fields": {"x": {"strategy": "doesNotExist"}}}
    out = await r.redact("Alice!", policy=policy)
    assert out.text == "Alice!"


@pytest.mark.asyncio
async def test_redact_with_empty_policy_returns_text() -> None:
    r = Redactor(detector=_StubDetector(), strategies={"mask": Mask()})
    out = await r.redact("Alice!", policy={})
    assert out.text == "Alice!"


@pytest.mark.asyncio
async def test_redact_with_policy_aggregates_relex_map() -> None:
    class _MultiDetector:
        name = "multi"

        async def detect(self, text, entity_types):
            return [
                Span(0, 5, "PERSON", 0.9),
                Span(10, 15, "EMAIL", 0.9),
            ]

        async def warmup(self):
            return None

    r = Redactor(
        detector=_StubDetector(),
        strategies={"autoDeID": AutoDeID(_MultiDetector())},
    )
    policy = {"fields": {"name_and_email": {"strategy": "autoDeID", "relex": True}}}
    out = await r.redact("Alice and a@b.c are friends", policy=policy)
    assert "Alice" in out.relex_map
    assert "a@b.c" in out.relex_map


@pytest.mark.asyncio
async def test_policy_redact_remaps_span_coords_to_original_text() -> None:
    class _TwoField:
        name = "two"

        async def detect(self, text, entity_types):
            want = set(entity_types or [])
            spans = []
            if (not want or "FIRST" in want) and text.startswith("Alice"):
                spans.append(Span(0, 5, "FIRST", 0.9))
            if (not want or "SECOND" in want) and "Smith" in text:
                idx = text.index("Smith")
                spans.append(Span(idx, idx + 5, "SECOND", 0.9))
            return spans

        async def warmup(self):
            return None

    r = Redactor(
        detector=_TwoField(),
        strategies={"autoDeID": AutoDeID(_TwoField())},
    )
    policy = {
        "fields": {
            "first": {
                "strategy": "autoDeID",
                "entity_types": ["FIRST"],
                "relex": False,
                "format": "[X]",
            },
            "second": {
                "strategy": "autoDeID",
                "entity_types": ["SECOND"],
                "relex": False,
                "format": "<Y>",
            },
        }
    }
    out = await r.redact("Alice Smith", policy=policy)
    assert out.text == "[X] <Y>"
    assert len(out.spans) == 2
    assert (out.spans[0].start, out.spans[0].end) == (0, 5)
    assert (out.spans[1].start, out.spans[1].end) == (6, 11)
