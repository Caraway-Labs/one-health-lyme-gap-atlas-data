from pathlib import Path


def test_vpc_worker_provisioning_preserves_private_graph_boundary() -> None:
    provisioner = Path("infra/Provision-PmcExtractionWorker.ps1").read_text(encoding="utf-8")
    configurator = Path("infra/Configure-PmcExtractionWorker.ps1").read_text(encoding="utf-8")
    installer = Path("infra/install-pmc-worker.sh").read_text(encoding="utf-8")
    assert "--vpc-uuid $VpcUuid" in provisioner
    assert "ports:22" in provisioner
    assert "7687" not in provisioner.split("firewall create", 1)[1].split("| Out-Null", 1)[0]
    assert "@${IMAGE_DIGEST}" in installer
    assert "pmc-extract --estimated-cost-usd 0.10 --confirm" in installer
    assert "Configure-PmcExtractionWorker.ps1" in provisioner
    assert '"NEO4J_URI=bolt://$Neo4jPrivateIp:7687"' in configurator
    assert "doctl registry docker-config oh-lyme-data --expiry-seconds 3600" in configurator
    assert "Worker SSH did not become ready; secret transfer was not attempted." in configurator
    assert "tr -d '\\r' </tmp/install-pmc-worker.sh" in configurator
    assert "SNOWFLAKE_PRIVATE_KEY_PATH', 'SNOWFLAKE_PRIVATE_KEY_B64" in configurator
    assert "[Convert]::ToBase64String([IO.File]::ReadAllBytes($keyPath))" in configurator
    assert '"SNOWFLAKE_PRIVATE_KEY_B64=$snowflakeKeyB64"' in configurator
    assert "trap 'rm -f /tmp/pmc-runtime.env /tmp/docker-config.json" in configurator


def test_vpc_worker_configuration_overrides_only_governed_runtime_values() -> None:
    configurator = Path("infra/Configure-PmcExtractionWorker.ps1").read_text(encoding="utf-8")
    assert (
        "'TOPX_ENV', 'PAPERS_REQUIRE_HUMAN_REVIEW', 'KG_CHAT_ENABLED', 'NEO4J_URI',"
    ) in configurator
    assert "PAPERS_REQUIRE_HUMAN_REVIEW=true" in configurator
    assert "KG_CHAT_ENABLED=false" in configurator
