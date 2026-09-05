from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.errors import internal_error, payload_too_large
from app.inference.detector import Span
from app.observability import CACHE_HITS, REQUEST_LATENCY, REQUESTS


class RedactRequest(BaseModel):
    text: str = Field(min_length=1)
    entity_types: list[str] | None = None
    policy: dict | None = None


class RedactResponse(BaseModel):
    text: str
    spans: list[Span]
    relex_map: dict[str, str]


def _audit_summary(spans: list[Span]) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for s in spans:
        grouped.setdefault(s.type, []).append(s.confidence)
    return [
        {
            "type": t,
            "count": len(confs),
            "confidence_avg": round(sum(confs) / len(confs), 3) if confs else 0.0,
        }
        for t, confs in grouped.items()
    ]


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.post("/v1/redact", response_model=RedactResponse)
    async def redact(
        request: Request,
        body: RedactRequest,
        api_key: Annotated[str, Depends(require_api_key)],
        x_idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> Any:
        from app.audit.backend import AuditEvent
        from app.ratelimit import rate_limit
        from app.state import model_state

        await rate_limit(api_key)

        start = time.perf_counter()
        endpoint = "POST /v1/redact"
        method = "POST"
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex

        try:
            settings = model_state.settings
            max_chars = getattr(settings, "max_text_chars", 100_000)
            if len(body.text) > max_chars:
                REQUESTS.labels(endpoint=endpoint, method=method, status="413").inc()
                return payload_too_large(  # type: ignore[return-value]
                    request, f"text exceeds {max_chars} chars"
                )
            redactor = model_state.redactor
            audit = model_state.audit
            job_store = getattr(model_state, "job_store", None)
            if redactor is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                return internal_error(request, "redactor not initialized")  # type: ignore[return-value]

            # Idempotency short-circuit
            if x_idempotency_key and job_store is not None:
                idem_raw = await job_store.client.get(f"redax:idem:{x_idempotency_key}")
                if idem_raw:
                    CACHE_HITS.labels(cache="idempotency").inc()
                    REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
                    return json.loads(idem_raw)

            # Response cache short-circuit
            cache_payload = {
                "text": body.text,
                "policy": body.policy or {},
                "entity_types": body.entity_types or [],
                "salt": getattr(settings, "hash_salt", "") or "",
            }
            cache_key = hashlib.sha256(
                json.dumps(cache_payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            if job_store is not None:
                cache_raw = await job_store.client.get(f"redax:cache:{cache_key}")
                if cache_raw:
                    CACHE_HITS.labels(cache="response").inc()
                    REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
                    return json.loads(cache_raw)

            inference_start = time.perf_counter()
            result = await redactor.redact(
                body.text, policy=body.policy, entity_types=body.entity_types
            )
            inference_ms = int((time.perf_counter() - inference_start) * 1000)

            response_body = {
                "text": result.text,
                "spans": [s.__dict__ for s in result.spans],
                "relex_map": result.relex_map,
            }

            ttl = getattr(settings, "cache_ttl_seconds", 3600)
            if job_store is not None:
                await job_store.client.set(
                    f"redax:cache:{cache_key}", json.dumps(response_body), ex=ttl
                )
                if x_idempotency_key:
                    idem_ttl = getattr(settings, "idempotency_ttl_seconds", 86_400)
                    await job_store.client.set(
                        f"redax:idem:{x_idempotency_key}",
                        json.dumps(response_body),
                        ex=idem_ttl,
                    )

            if audit is not None:
                version = (
                    "policy"
                    if isinstance(body.policy, dict) and body.policy.get("version")
                    else "default"
                )
                await audit.record(
                    AuditEvent(
                        request_id=request_id,
                        ts="",
                        policy_version=str(version),
                        text_chars=len(body.text),
                        entities_detected=_audit_summary(result.spans),
                        inference_ms=inference_ms,
                    )
                )

            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            return RedactResponse(
                text=response_body["text"],
                spans=result.spans,
                relex_map=response_body["relex_map"],
            )
        except Exception as exc:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            return internal_error(request, str(exc))  # type: ignore[return-value]
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    app.include_router(router)
