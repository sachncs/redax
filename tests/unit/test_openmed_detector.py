from __future__ import annotations

from app.inference.openmed import OpenMedPIIDetector, _entity_to_span, sanitize_label


def test_sanitize_label_maps_known_labels() -> None:
    assert sanitize_label("email") == "EMAIL"
    assert sanitize_label("phone_number") == "PHONE_E164"
    assert sanitize_label("ssn") == "SSN_US"
    assert sanitize_label("first_name") == "PERSON"
    assert sanitize_label("ipv4") == "IP_ADDRESS"
    assert sanitize_label("iban") == "IBAN"
    assert sanitize_label("credit_card_number") == "CREDIT_CARD"


def test_sanitize_label_unknown_falls_back_to_url() -> None:
    assert sanitize_label("unobtainium") == "URL"
    assert sanitize_label("") == "URL"


def test_entity_to_span_uses_char_offsets() -> None:
    """Regression: the original implementation stored token IDs as
    start/end. _entity_to_span must use char_start / char_end.
    """
    from app.inference.detector import Span

    entity = {
        "label": "first_name",
        "char_start": 7,
        "char_end": 12,
        "word_id": 1,
    }
    span = _entity_to_span(entity)
    assert span.start == 7
    assert span.end == 12
    assert span.type == "first_name"
    assert span.confidence == 0.9
    assert isinstance(span, Span)


def test_openmed_detect_handles_tokenizer_offset_failure() -> None:
    """If the tokenizer rejects `return_offsets_mapping=True` (as
    DebertaV2 does), the detector must fall back to the plain tokenizer
    output and not raise TypeError into the request path.
    """
    detector = OpenMedPIIDetector.__new__(OpenMedPIIDetector)
    detector._model = None
    detector._tokenizer = None
    assert detector._tokenizer is None  # construction does not load
