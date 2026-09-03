from pathlib import Path


def test_vpc_worker_provisioning_preserves_private_graph_boundary() -> None:
    provisioner = Path("infra/Provision-PmcExtractionWorker.ps1").read_text(encoding="utf-8")
    installer = Path("infra/install-pmc-worker.sh").read_text(encoding="utf-8")
    assert "--vpc-uuid $VpcUuid" in provisioner
    assert "ports:22" in provisioner
    assert "7687" not in provisioner.split("firewall create", 1)[1].split("| Out-Null", 1)[0]
    assert "@${IMAGE_DIGEST}" in installer
    assert "pmc-extract --estimated-cost-usd 0.10 --confirm" in installer
    assert "KG_CHAT_ENABLED=false" in provisioner
