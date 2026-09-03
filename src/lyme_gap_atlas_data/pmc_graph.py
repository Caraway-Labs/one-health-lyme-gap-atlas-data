"""PMC Open Access admission and atomic deterministic graph publication."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from lyme_gap_atlas_kg import EvidencePassageNode, GraphNode, PaperNode, SemanticEdge
from neo4j import Driver

_SPACE = re.compile(r"\s+")
_OPEN_LICENSE_HOSTS = ("creativecommons.org/licenses/", "creativecommons.org/publicdomain/")


def _nodes(root: ET.Element, name: str) -> list[ET.Element]:
    return [node for node in root.iter() if node.tag.rsplit("}", maxsplit=1)[-1] == name]


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
    pmcid = "".join(
        next(
            (
                node.text or ""
                for node in _nodes(root, "article-id")
                if node.attrib.get("pub-id-type") in {"pmc", "pmcid"}
            ),
            "",
        ).split()
    )
    if not pmcid.startswith("PMC"):
        raise ValueError("PMC identifier is missing")
    license_url = ""
    for license_node in _nodes(root, "license"):
        for link_node in license_node.iter():
            candidate = link_node.attrib.get("{http://www.w3.org/1999/xlink}href", "")
            if any(host in candidate.casefold() for host in _OPEN_LICENSE_HOSTS):
                license_url = candidate
                break
        if license_url:
            break
    if not license_url:
        raise ValueError("PMC Open Access license evidence is missing")
    body = next(iter(_nodes(root, "body")), None)
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


@dataclass(frozen=True)
class GraphContribution:
    paper: PaperNode
    nodes: list[GraphNode]
    passages: list[EvidencePassageNode]
    edges: list[SemanticEdge]


class Neo4jPaperPublisher:
    """Replace one paper's deterministic contribution in a single write transaction."""

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def publish(self, contribution: GraphContribution) -> dict[str, Any]:
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
