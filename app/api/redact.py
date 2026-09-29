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
from redis.exceptions import RedisError

from app.api.cache import (
    cache_envelope,
    decode_cache_envelope,
    redaction_cache_key,
    redaction_cache_payload,
)
from app.api.idempotency import complete as complete_idempotency
from app.api.idempotency import release as release_idempotency
from app.api.idempotency import reserve as reserve_idempotency
from app.api.models import EntityTypes
from app.api.policy import PolicyUnavailableError, effective_policy, policy_version
from app.audit.backend import Event, span_summary
from app.auth import principal_id, require_scope
from app.errors import (
    TRANSIENT_EXC,
    internal_error,
    payload_too_large,
    policy_unavailable,
    problem_response,
    timeout_error,
)
from app.inference.detector import Span
from app.jobs.store import JobStore
from app.logging import get_logger
from app.middleware import get_request_id
from app.observability import CACHE_HITS, REQUEST_LATENCY, REQUESTS
from app.ratelimit import rate_limit
from app.redaction.pipeline import PipelineUnavailableError
from app.state import State, get_state


class RedactRequest(BaseModel):
    """Request body for POST /v1/redact."""

    text: str = Field(min_length=1)
    entity_types: EntityTypes | None = None
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
CACHE_TRANSIENT_EXC: tuple[type[BaseException], ...] = (
    OSError,
    RedisError,
    TimeoutError,
)


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
        api_key: Annotated[str, Depends(require_scope("redact"))],
        x_idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        request_id: Annotated[str, Depends(get_request_id)] = "",
    ) -> Any:
        """Single-document redaction entry point; honours the idempotency and response caches."""
        await rate_limit(api_key, state)

        start = time.perf_counter()
        endpoint = "POST /v1/redact"
        method = "POST"
        idempotency_storage: str | None = None
        idempotency_token: str | None = None
        idempotency_completed = False
        job_store: JobStore | None = None

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
                    get_logger("redax.api").warning(
                        "redax.invalid_policy", error=exc.__class__.__name__
                    )
                    return problem_response(
                        request,
                        type="https://redax.ai/errors/invalid-policy",
                        title="Invalid Policy",
                        status=422,
                        detail="policy could not be validated",
                    )
            if policy is None and body.entity_types is None and not body.use_pipeline:
                try:
                    policy = effective_policy(settings, None, None)
                except PolicyUnavailableError:
                    REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                    return policy_unavailable(request)
                except (TypeError, ValueError) as exc:
                    REQUESTS.labels(endpoint=endpoint, method=method, status="422").inc()
                    get_logger("redax.api").warning(
                        "redax.invalid_policy", error=exc.__class__.__name__
                    )
                    return problem_response(
                        request,
                        type="https://redax.ai/errors/invalid-policy",
                        title="Invalid Policy",
                        status=422,
                        detail="policy could not be validated",
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
                    if job_store is None or job_store.client is None:
                        _log_cache_skipped("idempotency")
                    else:
                        ns = getattr(settings, "redis_namespace", "redax")
                        idempotency_storage = idempotency_storage_key(ns, x_idempotency_key)
                        reservation = await reserve_idempotency(
                            job_store.client,
                            idempotency_storage,
                            fingerprint,
                            getattr(settings, "idempotency_ttl_seconds", 86_400),
                        )
                        if reservation.status == "conflict":
                            REQUESTS.labels(endpoint=endpoint, method=method, status="409").inc()
                            return problem_response(
                                request,
                                type="https://redax.ai/errors/idempotency-key-reused",
                                title="Idempotency Key Reused",
                                status=409,
                                detail="Idempotency-Key must be reused with the same request body",
                            )
                        if reservation.status == "in_progress":
                            REQUESTS.labels(endpoint=endpoint, method=method, status="409").inc()
                            return problem_response(
                                request,
                                type="https://redax.ai/errors/idempotency-in-progress",
                                title="Idempotency Request In Progress",
                                status=409,
                                detail="Retry after the request holding this Idempotency-Key completes",
                            )
                        if reservation.status == "completed" and reservation.response is not None:
                            CACHE_HITS.labels(cache="idempotency").inc()
                            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
                            return reservation.response
                        idempotency_token = reservation.token

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
                if job_store is None or job_store.client is None:
                    _log_cache_skipped("response")
                else:
                    ns = getattr(settings, "redis_namespace", "redax")
                    try:
                        cache_raw = await job_store.client.get(f"{ns}:cache:{cache_key}")
                    except CACHE_TRANSIENT_EXC as exc:
                        _log_cache_skipped("response")
                        get_logger("redax.api").warning(
                            "redax.cache_read_failed", error=exc.__class__.__name__
                        )
                    else:
                        if cache_raw:
                            cached_response = decode_cache_envelope(cache_raw)
                            if cached_response is not None:
                                CACHE_HITS.labels(cache="response").inc()
                                REQUESTS.labels(
                                    endpoint=endpoint, method=method, status="200"
                                ).inc()
                                return cached_response

                inference_start = time.perf_counter()
                used_pipeline = False
                used_fallback = False
                digest: str | None = None

                pipeline = state.pipeline
                response_body: dict[str, Any]
                spans: list[Span]
                if body.use_pipeline:
                    if pipeline is None:
                        raise RuntimeError("redaction pipeline is not initialized")
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

                if audit is not None:
                    from app.observability.tracing import current_trace_id_hex

                    audit_kwargs: dict[str, Any] = dict(
                        request_id=request_id,
                        ts="",
                        policy_version=policy_version(policy),
                        text_chars=len(body.text),
                        principal_id=principal_id(api_key, getattr(settings, "hash_salt", "")),
                        entities_detected=span_summary(spans),
                        inference_ms=inference_ms,
                        trace_id=current_trace_id_hex() or "",
                    )
                    if used_fallback:
                        audit_kwargs["entities_detected"] = [
                            {"type": "__used_fallback__", "count": 1, "confidence_avg": 0.0},
                            *audit_kwargs["entities_detected"],
                        ]
                    if used_pipeline:
                        audit_kwargs["model_name"] = state.detector.name if state.detector else ""
                    await audit.record(Event(**audit_kwargs))

                # Publish replayable success only after the audit boundary has
                # acknowledged the event. A required-audit failure must not
                # leave a cache hit or completed idempotency record that turns
                # a later retry into an unaudited success.
                if x_idempotency_key and job_store is not None and job_store.client is not None:
                    idem_ttl = getattr(settings, "idempotency_ttl_seconds", 86_400)
                    if idempotency_storage is None or idempotency_token is None:
                        raise RuntimeError("idempotency reservation was not acquired")
                    if not await complete_idempotency(
                        job_store.client,
                        idempotency_storage,
                        fingerprint,
                        idempotency_token,
                        response_body,
                        idem_ttl,
                    ):
                        raise RuntimeError("idempotency reservation expired before completion")
                    idempotency_completed = True

                # Publish the optional response cache only after the idempotency
                # record is complete. This prevents a lease-expiry race from
                # leaving a cache hit without a durable same-key replay record.
                ttl = getattr(settings, "cache_ttl_seconds", 3600)
                if job_store is not None and job_store.client is not None:
                    ns = getattr(settings, "redis_namespace", "redax")
                    try:
                        await job_store.client.set(
                            f"{ns}:cache:{cache_key}",
                            json.dumps(cache_envelope(response_body)),
                            ex=ttl,
                        )
                    except CACHE_TRANSIENT_EXC as exc:
                        _log_cache_skipped("response")
                        get_logger("redax.api").warning(
                            "redax.cache_write_failed", error=exc.__class__.__name__
                        )

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
        except PipelineUnavailableError:
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return problem_response(
                request,
                type="https://redax.ai/errors/pipeline-unavailable",
                title="Pipeline Unavailable",
                status=503,
                detail="redaction pipeline is temporarily unavailable",
            )
        except TRANSIENT_EXC as exc:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            get_logger("redax.api").error("redax.redact_failed", error=exc.__class__.__name__)
            return internal_error(request)
        finally:
            if (
                idempotency_storage is not None
                and idempotency_token is not None
                and not idempotency_completed
            ):
                try:
                    if job_store is not None and job_store.client is not None:
                        await release_idempotency(
                            job_store.client, idempotency_storage, idempotency_token
                        )
                except TRANSIENT_EXC:
                    get_logger("redax.api").warning(
                        "redax.idempotency_release_failed", error="redis_error"
                    )
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    app.include_router(router)
