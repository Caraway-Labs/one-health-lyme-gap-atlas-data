"""PMC Open Access admission and atomic deterministic graph publication."""

from __future__ import annotations

import hashlib
import io
import re
import tarfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx
from lyme_gap_atlas_kg import (
    GraphContribution,
)
from neo4j import Driver

_SPACE = re.compile(r"\s+")
_OPEN_LICENSE_HOSTS = ("creativecommons.org/licenses/", "creativecommons.org/publicdomain/")


class PmcOpenAccessClient:
    """Fetch only an article package explicitly listed by the PMC OA service."""

    def fetch_jats(self, pmcid: str) -> bytes:
        if not re.fullmatch(r"PMC\d+", pmcid):
            raise ValueError("invalid PMCID")
        listing = httpx.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi",
            params={"id": pmcid},
            timeout=30,
        )
        listing.raise_for_status()
        root = ET.fromstring(listing.content)
        link = next(
            (
                item.attrib["href"]
                for item in root.findall(".//link")
                if item.attrib.get("format") == "tgz" and item.attrib.get("href")
            ),
            None,
        )
        if link is None:
            raise ValueError("PMC Open Access package is unavailable")
        package = httpx.get(link.replace("ftp://", "https://", 1), timeout=120)
        package.raise_for_status()
        with tarfile.open(fileobj=io.BytesIO(package.content), mode="r:gz") as archive:
            members = [member for member in archive.getmembers() if member.name.endswith(".nxml")]
            if len(members) != 1:
                raise ValueError("PMC package does not contain exactly one JATS article")
            extracted = archive.extractfile(members[0])
            if extracted is None:
                raise ValueError("PMC JATS article could not be extracted")
            return extracted.read()


@dataclass(frozen=True)
class AdmittedFullText:
    pmcid: str
    license_url: str
    normalized_text: str
    jats_sha256: str
    text_sha256: str


def admit_pmc_open_access(jats: bytes) -> AdmittedFullText:
    """Fail closed unless JATS declares English and an explicit open license."""
    root = ET.fromstring(jats)
    language = root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang", "").casefold()
    if language not in {"en", "eng", "english"}:
        raise ValueError("PMC article is not English")
    pmcid = "".join(root.findtext(".//article-id[@pub-id-type='pmc']", default="").split())
    if not pmcid.startswith("PMC"):
        raise ValueError("PMC identifier is missing")
    license_url = ""
    for license_node in root.findall(".//license"):
        candidate = license_node.attrib.get("{http://www.w3.org/1999/xlink}href", "")
        if any(host in candidate.casefold() for host in _OPEN_LICENSE_HOSTS):
            license_url = candidate
            break
    if not license_url:
        raise ValueError("PMC Open Access license evidence is missing")
    body = root.find(".//body")
    if body is None:
        raise ValueError("JATS body is missing")
    normalized = _SPACE.sub(" ", " ".join(body.itertext())).strip()
    if not normalized:
        raise ValueError("normalized full text is empty")
    return AdmittedFullText(
        pmcid=pmcid,
        license_url=license_url,
        normalized_text=normalized,
        jats_sha256=hashlib.sha256(jats).hexdigest(),
        text_sha256=hashlib.sha256(normalized.encode()).hexdigest(),
    )


class Neo4jPaperPublisher:
    """Replace one paper's deterministic contribution in a single write transaction."""

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def publish(self, contribution: GraphContribution) -> dict[str, object]:
        payload = {
            "paper": contribution.paper.model_dump(mode="json"),
            "nodes": [node.model_dump(mode="json") for node in contribution.nodes],
            "passages": [
                {**node.model_dump(mode="json"), "embedding": node.embedding}
                for node in contribution.passages
            ],
            "edges": [edge.model_dump(mode="json") for edge in contribution.edges],
        }
        with self._driver.session(database="neo4j") as session:
            result = session.execute_write(self._replace_paper, payload)
        return {
            **result,
            "node_count": len(contribution.nodes) + 1,
            "passage_count": len(contribution.passages),
            "edge_count": len(contribution.edges),
        }

    @staticmethod
    def _replace_paper(transaction: Any, payload: dict[str, Any]) -> dict[str, Any]:
        paper_id = payload["paper"]["id"]
        transaction.run(
            """MATCH (old:Paper {id: $paper_id})
               OPTIONAL MATCH (old)-[:HAS_PASSAGE]->(passage:EvidencePassage)
               OPTIONAL MATCH ()-[edge {paper_id: $paper_id}]-()
               DELETE edge, passage, old""",
            paper_id=paper_id,
        ).consume()
        transaction.run("CREATE (paper:Paper) SET paper = $paper", paper=payload["paper"]).consume()
        node_types = sorted({item["node_type"] for item in payload["nodes"]})
        for node_type in node_types:
            items = [item for item in payload["nodes"] if item["node_type"] == node_type]
            transaction.run(
                f"UNWIND $nodes AS item MERGE (node:KnowledgeNode:{node_type} "
                "{id: item.id}) SET node = item",
                nodes=items,
            ).consume()
        transaction.run(
            """UNWIND $passages AS item CREATE (passage:EvidencePassage)
               SET passage = item WITH passage
               MATCH (paper:Paper {id: passage.paper_id})
               CREATE (paper)-[:HAS_PASSAGE]->(passage)""",
            passages=payload["passages"],
        ).consume()
        relationship_types = sorted({item["relationship_type"] for item in payload["edges"]})
        for relationship_type in relationship_types:
            items = [
                item for item in payload["edges"] if item["relationship_type"] == relationship_type
            ]
            transaction.run(
                f"""UNWIND $edges AS item
                    MATCH (source {{id: item.source_node_id}}),
                          (target {{id: item.target_node_id}})
                    CREATE (source)-[edge:{relationship_type}]->(target) SET edge = item""",
                edges=items,
            ).consume()
        summary = transaction.run("RETURN randomUUID() AS transaction_id").single(strict=True)
        return {"neo4j_transaction_id": summary["transaction_id"], "paper_id": paper_id}
