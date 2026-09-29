from __future__ import annotations

import json
from pathlib import Path

import yaml


def test_kubernetes_network_policies_are_fail_closed_and_bound() -> None:
    path = Path(__file__).parents[2] / "deploy" / "kubernetes" / "network-policy.yaml"
    documents = list(yaml.safe_load_all(path.read_text()))
    assert {document["metadata"]["name"] for document in documents} == {
        "redax-api",
        "redax-worker",
    }
    api, worker = documents
    assert api["spec"]["policyTypes"] == ["Ingress", "Egress"]
    assert worker["spec"]["policyTypes"] == ["Ingress", "Egress"]
    assert "ingress" not in worker["spec"]
    allowed_ports = {rule["port"] for egress in api["spec"]["egress"] for rule in egress["ports"]}
    assert allowed_ports == {53, 443, 6379, 6380}
    assert api["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8000}]


def test_kubernetes_reference_uses_shared_audit_without_rw_volume() -> None:
    root = Path(__file__).parents[2]
    configmap = yaml.safe_load((root / "deploy/kubernetes/configmap.yaml").read_text())
    kustomization = yaml.safe_load((root / "deploy/kubernetes/kustomization.yaml").read_text())
    api_deployment = yaml.safe_load((root / "deploy/kubernetes/api-deployment.yaml").read_text())
    worker_deployment = yaml.safe_load(
        (root / "deploy/kubernetes/worker-deployment.yaml").read_text()
    )

    assert configmap["data"]["REDAX_AUDIT_BACKEND"] == "redis"
    assert configmap["data"]["REDAX_AUDIT_REDIS_MAX_EVENTS"] == "100000"
    assert "audit-pvc.yaml" not in kustomization["resources"]
    assert api_deployment["spec"]["template"]["spec"]["volumes"] == [
        {"name": "tmp", "emptyDir": {}}
    ]
    assert worker_deployment["spec"]["template"]["spec"]["volumes"] == [
        {"name": "tmp", "emptyDir": {}}
    ]


def test_monitoring_assets_cover_queue_age_retries_and_job_latency() -> None:
    root = Path(__file__).parents[2]
    rules = yaml.safe_load((root / "deploy/monitoring/prometheus-rules.yaml").read_text())
    rule_names = {rule["alert"] for group in rules["spec"]["groups"] for rule in group["rules"]}
    assert {"RedaxQueueAgeHigh", "RedaxJobRetriesIncreasing"} <= rule_names

    dashboard = json.loads((root / "deploy/monitoring/redax-dashboard.json").read_text())
    job_panel = next(
        panel
        for panel in dashboard["panels"]
        if panel["title"] == "Durable job latency and retries"
    )
    expressions = {target["expr"] for target in job_panel["targets"]}
    assert any("redax_job_duration_seconds_bucket" in expression for expression in expressions)
    assert any("redax_job_retries_total" in expression for expression in expressions)
