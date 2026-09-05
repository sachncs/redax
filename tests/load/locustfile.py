"""Locust load test for /v1/redact at sustained 50 RPS.

Usage:
    pip install locust
    locust -f tests/load/locustfile.py --host http://localhost:8000
"""
from __future__ import annotations

from locust import HttpUser, between, task

SAMPLE = (
    "Reach Dr. Adam Wilson at adam@example.com or +1 415-555-2671. "
    "His IBAN is GB00FAKE00000000000000 and card 4532 0151 1283 0366. "
    "Server at 10.0.0.1 went down. SSN 000-00-0000."
)


class RedaxUser(HttpUser):
    wait_time = between(0.01, 0.05)

    @task(3)
    def redact_sync(self) -> None:
        self.client.post("/v1/redact", json={"text": SAMPLE})

    @task(1)
    def redact_batch(self) -> None:
        self.client.post(
            "/v1/redact/batch",
            json={"items": [{"text": SAMPLE}, {"text": SAMPLE}, {"text": SAMPLE}]},
        )
