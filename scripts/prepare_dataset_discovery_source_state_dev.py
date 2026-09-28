"""Persist bounded, labeled DEV source-state recommendation fixtures via runtime API.

Requires the standalone Dataset Discovery package on PYTHONPATH and the
role-restricted service PAT path in DATASET_DISCOVERY_PAT_FILE. No catalog,
governed-source, approval, ingestion, or publication writes are performed.
"""

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

import snowflake.connector
from lyme_gap_atlas_dataset_discovery.adapters.snowflake_repository import (
    SnowflakeRecommendationRepository,
)
from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    CandidateAnalysis,
    Classification,
    RationaleClaim,
    render_rationale,
)
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    EvidenceRef,
    ObservedFact,
    RecommendationIdentity,
    RunCreateMetadata,
    RunFinalizationReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import (
    RecommendationWrite,
    assertion_sha256,
    rights_evidence_state,
)
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    Dimension,
    PriorityInput,
    RankingDimensions,
    Relationship,
    rank_candidate,
)
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult

SNAPSHOT = "7b027ee2-e881-4c5d-9bd3-a1c6477795bb"
FIXTURES = {
    "exact_duplicate": (
        "candidate:55f7f2e13d5b598d390c0caed44b62e9",
        Relationship.EXACT_DUPLICATE,
        "EXACT_RESOURCE_KEY",
        "LANDING_PAGE",
    ),
    "controlled_access": (
        "candidate:d1ff6c4a9f6f1c9e91d50ab9fa507a11",
        Relationship.UNKNOWN,
        "NO_DETERMINISTIC_LINK",
        "CONTROLLED_ACCESS",
    ),
}


def one(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", choices=FIXTURES)
    args = parser.parse_args()
    resource, relationship_type, relationship_basis, resource_type = FIXTURES[args.fixture]
    token = Path(os.environ["DATASET_DISCOVERY_PAT_FILE"]).read_text(encoding="utf-8").strip()
    with snowflake.connector.connect(
        account="TXB06009",
        user="OH_LYME_DEV_DATASET_DISCOVERY_SVC",
        authenticator="PROGRAMMATIC_ACCESS_TOKEN",
        token=token,
        role="OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME",
        database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        warehouse="OH_LYME_DEV_INGEST_XS_WH",
        session_parameters={"QUERY_TAG": "data450-source-state-fixture"},
    ) as connection:
        if one(
            connection,
            "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()",
        ) != (
            "OH_LYME_DEV_DATASET_DISCOVERY_SVC",
            "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        ):
            raise RuntimeError("Unexpected runtime identity")
        candidate = one(
            connection,
            "SELECT s.catalog_dataset_id,s.catalog_resource_id,s.resource_type,"
            "o.observation_id,o.observed_at,o.metadata_sha256,o.field_values:title::VARCHAR "
            "FROM DATASET_DISCOVERY.V_CANDIDATE_SUMMARY s "
            "JOIN DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS o "
            "ON o.discovery_run_id=s.discovery_run_id AND o.resource_key=s.resource_key "
            "AND o.catalog_dataset_id=s.catalog_dataset_id "
            "AND o.catalog_resource_id=s.catalog_resource_id "
            "WHERE s.discovery_run_id=%s AND s.resource_key=%s "
            "AND o.field_values:title::VARCHAR IS NOT NULL ORDER BY o.observation_id LIMIT 1",
            (SNAPSHOT, resource),
        )
        if candidate is None or candidate[2] != resource_type:
            raise ValueError("Expected retained catalog fixture is unavailable")
        dataset, catalog_resource, _, observation, observed_at, sha, title = candidate
        if args.fixture == "exact_duplicate":
            link = one(
                connection,
                "SELECT relationship,relationship_basis FROM "
                "DATASET_DISCOVERY.V_CANDIDATE_IDENTITY_LINKS "
                "WHERE discovery_run_id=%s AND resource_key=%s "
                "AND catalog_resource_id=%s AND relationship='EXACT_DUPLICATE' LIMIT 1",
                (SNAPSHOT, resource, catalog_resource),
            )
            if link != ("EXACT_DUPLICATE", relationship_basis):
                raise ValueError("Exact duplicate lacks retained canonical identity link")

        repository = SnowflakeRecommendationRepository(connection)
        run_id = f"data450-{args.fixture}-{uuid.uuid4().hex}"
        version = hashlib.sha256(
            ("recommendation-version-v1\x1f" + run_id + "\x1f" + resource).encode()
        ).hexdigest()
        recommendation = hashlib.sha256(("recommendation-v1\x1f" + resource).encode()).hexdigest()
        ref = EvidenceRef(
            observation_id=observation,
            catalog_dataset_id=dataset,
            catalog_resource_id=catalog_resource,
            metadata_sha256=sha,
            observed_at=observed_at.isoformat(),
        )
        analysis = CandidateAnalysis(
            identity=CandidateIdentity(
                resource_key=resource,
                catalog_dataset_id=dataset,
                catalog_resource_id=catalog_resource,
            ),
            classification=Classification.POSSIBLY_RELEVANT,
            observed_facts=(ObservedFact(field="title", value=title, evidence=ref),),
            rationale_claims=(
                RationaleClaim(
                    field="title",
                    text=title,
                    kind="OBSERVED",
                    supporting_observation_ids=(observation,),
                ),
            ),
        )
        ranking = PriorityInput(
            resource_key=resource,
            recommendation_version_id=version,
            observed_evidence_ids=frozenset({observation}),
            relationship=relationship_type,
            dimensions=RankingDimensions(
                relevance=Dimension(value=1, supporting_observation_ids=(observation,)),
                geography=Dimension(),
                variables=Dimension(),
                time=Dimension(),
                provenance=Dimension(),
                freshness=Dimension(),
                rights_clarity=Dimension(),
                complementarity=Dimension(),
            ),
        )
        priority = rank_candidate(ranking)
        relationship = RelationshipResult(
            relationship=relationship_type,
            basis=relationship_basis,
            supporting_observation_ids=(observation,),
        )
        write = RecommendationWrite(
            operation_key=f"recommendation:{run_id}:{resource}",
            identity=RecommendationIdentity(
                recommendation_id=recommendation,
                recommendation_version_id=version,
                run_id=run_id,
                resource_key=resource,
            ),
            evidence_snapshot_id=SNAPSHOT,
            rights_state=rights_evidence_state(analysis),
            assertion_sha256=assertion_sha256(analysis, ranking, priority, relationship),
            analysis=analysis,
            ranking_input=ranking,
            priority=priority,
            relationship=relationship,
            rationale=render_rationale(analysis.rationale_claims),
        )
        run = repository.create_run(
            operation_key=f"run:{run_id}",
            run_id=run_id,
            metadata=RunCreateMetadata(
                mode="DEV_MANUAL",
                trigger_type="MANUAL",
                code_sha="0" * 40,
                spec_version="data450-source-state-acceptance-v1",
                graph_version="v1",
                config_fingerprint="0" * 64,
                search_fingerprint="0" * 64,
                evidence_snapshot_id=SNAPSHOT,
            ),
        )
        receipt = repository.save_recommendation(write)
        final = repository.finalize_run(
            RunFinalizationReceipt(
                operation_key=f"finalize:{run_id}",
                run_id=run_id,
                status="SUCCEEDED_WITH_RECOMMENDATIONS",
                processed_count=1,
                recommendation_count=1,
            )
        )
        print(
            json.dumps(
                {
                    "fixture": args.fixture,
                    "run": run.run_id,
                    "recommendation": receipt.identity.recommendation_id,
                    "version": version,
                    "resource": resource,
                    "observation": observation,
                    "relationship": relationship_type.value,
                    "resource_type": resource_type,
                    "status": final.status,
                }
            )
        )


if __name__ == "__main__":
    main()
