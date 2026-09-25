"""Single-document redaction endpoint (``POST /v1/redact``).

Supports the legacy one-shot ``Redactor`` path and the newer
multi-stage ``Pipeline`` path (``body.use_pipeline``). Optionally
honours an ``Idempotency-Key`` header and the response cache.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from pydantic import BaseModel, Field

from app.api.cache import redaction_cache_key, redaction_cache_payload
from app.api.policy import effective_policy, policy_version
from app.audit.backend import Event, span_summary
from app.auth import require_api_key
from app.errors import (
    TRANSIENT_EXC,
    internal_error,
    payload_too_large,
    problem_response,
    timeout_error,
)
from app.inference.detector import Span
from app.logging import get_logger
from app.middleware import get_request_id
from app.observability import CACHE_HITS, REQUEST_LATENCY, REQUESTS
from app.ratelimit import rate_limit
from app.state import State, get_state


class RedactRequest(BaseModel):
    """Request body for POST /v1/redact."""

    text: str = Field(min_length=1)
    entity_types: list[str] | None = None
    policy: dict[str, Any] | None = None
    use_pipeline: bool = False


class RedactResponse(BaseModel):
    """Response body for POST /v1/redact."""

    text: str
    spans: list[Span]
    relex_map: dict[str, str]
    used_pipeline: bool = False
    used_fallback: bool = False
    digest: str | None = None


_CACHE_SKIPPED_LOGGED: set[str] = set()
IDEMPOTENCY_RESPONSE_VERSION = 2


def request_fingerprint(body: RedactRequest, policy: dict[str, Any] | None) -> str:
    """Hash the complete effective request for safe idempotency reuse."""
    payload = {
        "text": body.text,
        "entity_types": body.entity_types or [],
        "policy": policy or {},
        "use_pipeline": body.use_pipeline,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _log_cache_skipped(name: str) -> None:
    """Log once per process when a cache lookup is silently dropped."""
    if name in _CACHE_SKIPPED_LOGGED:
        return
    _CACHE_SKIPPED_LOGGED.add(name)
    get_logger("redax.api").warning("redax.cache_skipped", cache=name)


def idempotency_storage_key(namespace: str, key: str) -> str:
    """Return a Redis key that does not persist the caller's header value."""
    digest = hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()
    return f"{namespace}:idem:{digest}"


def register(app: FastAPI) -> None:
    """Mount the POST /v1/redact route on ``app``."""

    router = APIRouter()

    @router.post("/v1/redact", response_model=RedactResponse)
    async def redact(
        request: Request,
        body: RedactRequest,
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_api_key)],
        x_idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        request_id: Annotated[str, Depends(get_request_id)] = "",
    ) -> Any:
        """Single-document redaction entry point; honours the idempotency and response caches."""
        await rate_limit(api_key, state)

        start = time.perf_counter()
        endpoint = "POST /v1/redact"
        method = "POST"

        try:
            settings = state.settings
            max_chars = getattr(settings, "max_text_chars", 100_000)
            if len(body.text) > max_chars:
                REQUESTS.labels(endpoint=endpoint, method=method, status="413").inc()
                return payload_too_large(request, f"text exceeds {max_chars} chars")
            policy = body.policy
            if body.policy is not None and body.entity_types is not None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="422").inc()
                return problem_response(
                    request,
                    type="https://redax.ai/errors/policy-entity-types-conflict",
                    title="Policy and Entity Types Conflict",
                    status=422,
                    detail="Choose either policy or entity_types; do not send both.",
                )
            if body.use_pipeline and (body.policy is not None or body.entity_types is not None):
                REQUESTS.labels(endpoint=endpoint, method=method, status="422").inc()
                return problem_response(
                    request,
                    type="https://redax.ai/errors/pipeline-policy-conflict",
                    title="Pipeline Policy Conflict",
                    status=422,
                    detail=(
                        "use_pipeline=true uses the staged typed-placeholder contract; "
                        "omit policy and entity_types or use the policy redactor path."
                    ),
                )
            if policy is not None:
                try:
                    policy = effective_policy(settings, policy, body.entity_types)
                except (TypeError, ValueError) as exc:
                    REQUESTS.labels(endpoint=endpoint, method=method, status="422").inc()
                    return problem_response(
                        request,
                        type="https://redax.ai/errors/invalid-policy",
                        title="Invalid Policy",
                        status=422,
                        detail=str(exc),
                    )
            if policy is None and body.entity_types is None and not body.use_pipeline:
                try:
                    policy = effective_policy(settings, None, None)
                except (TypeError, ValueError) as exc:
                    REQUESTS.labels(endpoint=endpoint, method=method, status="422").inc()
                    return problem_response(
                        request,
                        type="https://redax.ai/errors/invalid-policy",
                        title="Invalid Policy",
                        status=422,
                        detail=str(exc),
                    )
            pipeline = state.pipeline
            if body.use_pipeline and pipeline is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="422").inc()
                return problem_response(
                    request,
                    type="https://redax.ai/errors/pipeline-unavailable",
                    title="Pipeline Unavailable",
                    status=422,
                    detail="use_pipeline=true requested but no pipeline is configured",
                )
            redactor = state.redactor
            audit = state.audit
            job_store = state.job_store
            if redactor is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                return internal_error(request, "redactor not initialized")

            timeout_seconds = getattr(settings, "request_timeout_seconds", 30.0)
            async with asyncio.timeout(timeout_seconds):
                fingerprint = request_fingerprint(body, policy)
                # Idempotency short-circuit
                if x_idempotency_key:
                    if job_store is None:
                        _log_cache_skipped("idempotency")
                    else:
                        ns = getattr(settings, "redis_namespace", "redax")
                        idem_raw = await job_store.client.get(
                            idempotency_storage_key(ns, x_idempotency_key)
                        )
                        if idem_raw:
                            idem_payload = json.loads(idem_raw)
                            if (
                                isinstance(idem_payload, dict)
                                and idem_payload.get("response_version")
                                == IDEMPOTENCY_RESPONSE_VERSION
                                and "response" in idem_payload
                            ):
                                if idem_payload.get("request_fingerprint") != fingerprint:
                                    return problem_response(
                                        request,
                                        type="https://redax.ai/errors/idempotency-key-reused",
                                        title="Idempotency Key Reused",
                                        status=409,
                                        detail="Idempotency-Key must be reused with the same request body",
                                    )
                                cached_response = idem_payload["response"]
                            else:
                                # Entries written before the fingerprinted
                                # envelope may contain the old response shape;
                                # recompute instead of replaying it.
                                cached_response = None
                            if cached_response is None:
                                idem_raw = None
                            else:
                                CACHE_HITS.labels(cache="idempotency").inc()
                                REQUESTS.labels(
                                    endpoint=endpoint, method=method, status="200"
                                ).inc()
                                return cached_response

                # Response cache short-circuit
                cache_shared = bool(getattr(settings, "cache_shared", False))
                cache_key = redaction_cache_key(
                    redaction_cache_payload(
                        body.text,
                        policy,
                        body.entity_types,
                        getattr(settings, "hash_salt", "") or "",
                        shared=cache_shared,
                        mode="pipeline" if body.use_pipeline else "legacy",
                        detector=getattr(settings, "detector", ""),
                        model_revision=getattr(settings, "model_revision", ""),
                    )
                )
                if job_store is None:
                    _log_cache_skipped("response")
                else:
                    ns = getattr(settings, "redis_namespace", "redax")
                    cache_raw = await job_store.client.get(f"{ns}:cache:{cache_key}")
                    if cache_raw:
                        CACHE_HITS.labels(cache="response").inc()
                        REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
                        return json.loads(cache_raw)

                inference_start = time.perf_counter()
                used_pipeline = False
                used_fallback = False
                digest: str | None = None

                pipeline = state.pipeline
                response_body: dict[str, Any]
                spans: list[Span]
                if body.use_pipeline:
                    assert pipeline is not None  # checked above
                    pipeline_result = await pipeline(body.text)
                    spans = list(pipeline_result.spans)
                    inference_ms = int(pipeline_result.total_latency_ms)
                    used_pipeline = True
                    used_fallback = pipeline_result.used_fallback
                    digest = pipeline_result.digest
                    pipeline_spans: list[dict[str, Any]] = [
                        {
                            "start": s.start,
                            "end": s.end,
                            "type": s.type,
                            "confidence": s.confidence,
                        }
                        for s in spans
                    ]
                    relex_map: dict[str, str] = {}
                    response_body = {
                        "text": pipeline_result.text,
                        "spans": pipeline_spans,
                        "relex_map": relex_map,
                    }
                else:
                    result = await redactor.redact(
                        body.text, policy=policy, entity_types=body.entity_types
                    )
                    inference_ms = int((time.perf_counter() - inference_start) * 1000)
                    spans = list(result.spans)
                    response_body = {
                        "text": result.text,
                        "spans": [s.__dict__ for s in result.spans],
                        # Re-identification maps contain original values and
                        # must never cross the HTTP boundary.
                        "relex_map": {},
                    }

                ttl = getattr(settings, "cache_ttl_seconds", 3600)
                if job_store is not None:
                    ns = getattr(settings, "redis_namespace", "redax")
                    await job_store.client.set(
                        f"{ns}:cache:{cache_key}",
                        json.dumps(response_body),
                        ex=ttl,
                    )
                    if x_idempotency_key:
                        idem_ttl = getattr(settings, "idempotency_ttl_seconds", 86_400)
                        await job_store.client.set(
                            idempotency_storage_key(ns, x_idempotency_key),
                            json.dumps(
                                {
                                    "response_version": IDEMPOTENCY_RESPONSE_VERSION,
                                    "request_fingerprint": fingerprint,
                                    "response": response_body,
                                }
                            ),
                            ex=idem_ttl,
                        )

                if audit is not None:
                    from app.observability.tracing import current_trace_id_hex

                    audit_kwargs: dict[str, Any] = dict(
                        request_id=request_id,
                        ts="",
                        policy_version=policy_version(policy),
                        text_chars=len(body.text),
                        entities_detected=span_summary(spans),
                        inference_ms=inference_ms,
                        trace_id=current_trace_id_hex() or "",
                    )
                    if used_pipeline:
                        audit_kwargs["model_name"] = state.detector.name if state.detector else ""
                    await audit.record(Event(**audit_kwargs))

                REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
                response_text: str = str(response_body["text"])
                response_relex_map = {k: str(v) for k, v in response_body["relex_map"].items()}
                return RedactResponse(
                    text=response_text,
                    spans=spans,
                    relex_map=response_relex_map,
                    used_pipeline=used_pipeline,
                    used_fallback=used_fallback,
                    digest=digest,
                )
        except TimeoutError:
            REQUESTS.labels(endpoint=endpoint, method=method, status="504").inc()
            return timeout_error(request)
        except TRANSIENT_EXC as exc:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            get_logger("redax.api").error("redax.redact_failed", error=exc.__class__.__name__)
            return internal_error(request)
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    app.include_router(router)
