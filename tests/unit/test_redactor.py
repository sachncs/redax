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
