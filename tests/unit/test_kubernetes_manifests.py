from __future__ import annotations

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
