from __future__ import annotations

import pytest

from scripts.load_bench import request_payload, stream_completed


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("redact", {"text": "synthetic"}),
        ("batch", {"items": [{"text": "synthetic"}, {"text": "synthetic"}]}),
        ("stream", {"text": "synthetic", "chunk_chars": 100}),
    ],
)
def test_request_payload_builds_bounded_synthetic_workload(mode: str, expected: dict) -> None:
    assert request_payload(mode, "synthetic") == expected


def test_request_payload_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unsupported benchmark mode"):
        request_payload("unknown", "synthetic")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('data: {"text": "safe"}\n\ndata: [DONE]\n\n', True),
        ('data: {"error": "internal error"}\n\n', False),
        ('data: {"text": "safe"}\n\n', False),
    ],
)
def test_stream_completed_requires_terminal_success(body: str, expected: bool) -> None:
    assert stream_completed(body) is expected
