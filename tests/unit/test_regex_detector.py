from __future__ import annotations

import pytest

from app.inference.regex import RegexDetector, luhn_ok


@pytest.mark.asyncio
async def test_detects_email() -> None:
    d = RegexDetector()
    spans = await d.detect("Contact me at user@example.com please", [])
    assert len(spans) == 1
    assert spans[0].type == "EMAIL"
    assert spans[0].start == 14
    assert spans[0].end == 30


@pytest.mark.asyncio
async def test_detects_credit_card_with_luhn() -> None:
    d = RegexDetector()
    valid = "Card 4532 0151 1283 0366 works"
    invalid = "Card 4532 0151 1283 0367 nope"
    spans_v = await d.detect(valid, [])
    spans_i = await d.detect(invalid, [])
    assert any(s.type == "CREDIT_CARD" for s in spans_v)
    assert not any(s.type == "CREDIT_CARD" for s in spans_i)


@pytest.mark.asyncio
async def test_detects_phone() -> None:
    d = RegexDetector()
    spans = await d.detect("Call +1 415-555-2671 tomorrow", [])
    assert any(s.type == "PHONE_E164" for s in spans)


@pytest.mark.asyncio
async def test_detects_ip() -> None:
    d = RegexDetector()
    spans = await d.detect("server 192.168.1.1 is down", [])
    assert any(s.type == "IP_ADDRESS" for s in spans)


@pytest.mark.asyncio
async def test_entity_types_filter() -> None:
    d = RegexDetector()
    text = "email a@b.com and 10.0.0.1 ip"
    spans = await d.detect(text, ["EMAIL"])
    assert all(s.type == "EMAIL" for s in spans)
    assert len(spans) == 1


@pytest.mark.asyncio
async def test_sorted_by_offset() -> None:
    d = RegexDetector()
    spans = await d.detect("a@b.com then 10.0.0.1", [])
    assert spans == sorted(spans, key=lambda s: s.start)


def test_luhn_ok_examples() -> None:
    assert luhn_ok("4532015112830366")
    assert luhn_ok("4532 0151 1283 0366")
    assert not luhn_ok("4532015112830367")
    assert not luhn_ok("1234567890")
