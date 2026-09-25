from __future__ import annotations

import asyncio

from app.inference.regex import RegexDetector
from app.redaction.circuit.breaker import Breaker
from app.redaction.pipeline import Pipeline
from app.redaction.stages.gate import Gate
from app.redaction.stages.model import ModelStage


def build_pipeline(salt: str) -> Pipeline:
    detector = RegexDetector()
    return Pipeline(
        regex_gate=Gate(detector=detector),
        model_stage=ModelStage(detector=detector),
        model_breaker=Breaker(name="digest", threshold=3, cooldown_s=5.0),
        digest_salt=salt,
    )


def test_pipeline_digest_is_keyed_by_deployment_salt() -> None:
    text = "Contact alice@example.com"

    first = asyncio.run(build_pipeline("salt-a")(text))
    same = asyncio.run(build_pipeline("salt-a")(text))
    different = asyncio.run(build_pipeline("salt-b")(text))

    assert first.digest == same.digest
    assert first.digest != different.digest
