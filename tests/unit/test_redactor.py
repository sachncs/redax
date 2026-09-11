from __future__ import annotations

import pytest

from app.inference.detector import Span
from app.redaction.redactor import Redactor
from app.redaction.strategy import Deid, Mask, Skip


class StubDetector:
    """Test detector that finds a PERSON span only in the literal text 'Alice!'."""

    name = "stub"

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        return [Span(0, 5, "PERSON", 0.9)] if text == "Alice!" else []

    async def warmup(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redact_with_no_policy_uses_plain_path() -> None:
    r = Redactor(detector=StubDetector(), strategies={"mask": Mask()})
    out = await r.redact("Alice!")
    assert out.text == "[REDACTED]!"


@pytest.mark.asyncio
async def test_redact_with_policy_runs_strategies_in_order() -> None:
    r = Redactor(
        detector=StubDetector(),
        strategies={
            "passThrough": Skip(),
            "autoDeID": Deid(StubDetector()),
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
    r = Redactor(detector=StubDetector(), strategies={"mask": Mask()})
    policy = {"fields": {"x": {"strategy": "doesNotExist"}}}
    out = await r.redact("Alice!", policy=policy)
    assert out.text == "Alice!"


@pytest.mark.asyncio
async def test_redact_with_empty_policy_returns_text() -> None:
    r = Redactor(detector=StubDetector(), strategies={"mask": Mask()})
    out = await r.redact("Alice!", policy={})
    assert out.text == "Alice!"


@pytest.mark.asyncio
async def test_redact_with_policy_aggregates_relex_map() -> None:
    class MultiDetector:
        """Test detector that always returns PERSON + EMAIL spans."""

        name = "multi"

        async def detect(self, text, entity_types):
            return [
                Span(0, 5, "PERSON", 0.9),
                Span(10, 15, "EMAIL", 0.9),
            ]

        async def warmup(self):
            return None

    r = Redactor(
        detector=StubDetector(),
        strategies={"autoDeID": Deid(MultiDetector())},
    )
    policy = {"fields": {"name_and_email": {"strategy": "autoDeID", "relex": True}}}
    out = await r.redact("Alice and a@b.c are friends", policy=policy)
    assert "Alice" in out.relex_map
    assert "a@b.c" in out.relex_map


@pytest.mark.asyncio
async def test_policy_redact_remaps_span_coords_to_original_text() -> None:
    class TwoFieldDetector:
        """Test detector that finds FIRST and SECOND spans based on entity_types filters."""

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
        detector=TwoFieldDetector(),
        strategies={"autoDeID": Deid(TwoFieldDetector())},
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


@pytest.mark.asyncio
async def test_plain_substitutes_each_detected_span_with_replacement() -> None:
    """The single-shot Redactor.plain() path returns one substitution per Span."""
    from app.redaction.redactor import RedactionResult

    r = Redactor(
        detector=StubDetector(),
        strategies={"mask": Mask()},
        replacement="<X>",
    )
    out: RedactionResult = await r.plain("Alice!", entity_types=None)
    assert out.text == "<X>!"
    assert len(out.spans) == 1
    assert out.spans[0].type == "PERSON"


@pytest.mark.asyncio
async def test_plain_filters_entity_types() -> None:
    """``entity_types`` is forwarded to the detector in the plain path."""
    captured: dict[str, list[str] | None] = {}

    class CapturingDetector:
        name = "capture"

        async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
            captured["labels"] = entity_types
            return []

        async def warmup(self) -> None:
            return None

    r = Redactor(
        detector=CapturingDetector(),
        strategies={"mask": Mask()},
    )
    await r.plain("hello", entity_types=["EMAIL"])
    assert captured["labels"] == ["EMAIL"]
