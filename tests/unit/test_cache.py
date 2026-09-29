from __future__ import annotations

import json

from app.api.cache import cache_envelope, decode_cache_envelope


def test_cache_envelope_round_trips_current_schema() -> None:
    response = {"text": "safe", "spans": [], "relex_map": {}}

    assert decode_cache_envelope(json.dumps(cache_envelope(response))) == response


def test_cache_decoder_rejects_legacy_and_corrupt_values() -> None:
    assert decode_cache_envelope('{"text":"safe"}') is None
    assert decode_cache_envelope("not-json") is None
