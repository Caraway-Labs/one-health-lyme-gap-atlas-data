"""Bounded DEV-only Data #449 recommendation adapter probe.

Run with the standalone Dataset Discovery package importable and
DATASET_DISCOVERY_PAT_FILE set to the local role-restricted runtime PAT path.
This writes an explicitly labeled test run, never a governed source decision.
"""

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import snowflake.connector
from lyme_gap_atlas_dataset_discovery.adapters.snowflake_repository import (
    SnowflakeRecommendationRepository,
)
from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    CandidateAnalysis,
    Classification,
    RationaleClaim,
    SearchExpansionProposal,
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


def connect():
    token_path = Path(os.environ["DATASET_DISCOVERY_PAT_FILE"])
    token = token_path.read_text(encoding="utf-8").strip()
    return snowflake.connector.connect(
        account="TXB06009",
        user="OH_LYME_DEV_DATASET_DISCOVERY_SVC",
        authenticator="PROGRAMMATIC_ACCESS_TOKEN",
        token=token,
        role="OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME",
        database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        warehouse="OH_LYME_DEV_INGEST_XS_WH",
        session_parameters={"QUERY_TAG": "data-449-dev-acceptance-fixture"},
    )


def one(connection, sql, params=()):
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
        return cursor.fetchone()
    finally:
        cursor.close()


def main():
    connection = connect()
    try:
        assert one(
            connection,
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()",
        ) == (
            "OH_LYME_DEV_DATASET_DISCOVERY_SVC",
            "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        )
        candidate = one(
            connection,
            "SELECT s.discovery_run_id, s.resource_key, s.catalog_dataset_id, "
            "s.catalog_resource_id, o.observation_id, o.observed_at, "
            "o.metadata_sha256, o.field_values:title::VARCHAR "
            "FROM DATASET_DISCOVERY.V_CANDIDATE_SUMMARY s "
            "JOIN DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS o "
            "ON o.discovery_run_id = s.discovery_run_id "
            "AND o.resource_key = s.resource_key "
            "WHERE o.field_values:title::VARCHAR ILIKE '%Lyme%' "
            "AND s.discovery_run_id IN "
            "(SELECT discovery_run_id FROM DATASET_DISCOVERY.V_DISCOVERY_CONTEXT "
            "WHERE status = 'COMPLETED') "
            "ORDER BY s.discovery_run_id, s.resource_key LIMIT 1",
        )
        if candidate is None:
            raise RuntimeError("No eligible retained DEV Lyme title for bounded fixture")
        snapshot, resource, dataset, catalog_resource, observation, observed_at, sha, title = (
            candidate
        )
        run_id = "data449-acceptance-" + uuid.uuid4().hex
        repository = SnowflakeRecommendationRepository(connection)
        metadata = RunCreateMetadata(
            mode="DEV_MANUAL",
            trigger_type="MANUAL",
            code_sha="0" * 40,
            spec_version="data-449-acceptance-fixture-v1",
            graph_version="v1",
            config_fingerprint="0" * 64,
            search_fingerprint="0" * 64,
            evidence_snapshot_id=snapshot,
        )
        run = repository.create_run(operation_key=f"run:{run_id}", run_id=run_id, metadata=metadata)
        assert repository.get_run(run.operation_key) == run
        recommendation_id = hashlib.sha256(
            ("recommendation-v1\x1f" + resource).encode()
        ).hexdigest()
        version_id = hashlib.sha256(
            ("recommendation-version-v1\x1f" + run_id + "\x1f" + resource).encode()
        ).hexdigest()
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
            search_expansion_proposals=(
                SearchExpansionProposal(
                    proposed_term="Lyme",
                    catalog_scope="DEV_ACCEPTANCE_TEST_ONLY",
                    rationale="Test proposal from observed title; inactive search policy",
                    supporting_observation_ids=(observation,),
                ),
            ),
        )
        ranking = PriorityInput(
            resource_key=resource,
            recommendation_version_id=version_id,
            observed_evidence_ids=frozenset({observation}),
            relationship=Relationship.UNKNOWN,
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
            relationship=Relationship.UNKNOWN,
            basis="NO_DETERMINISTIC_LINK",
            supporting_observation_ids=(observation,),
        )
        request = RecommendationWrite(
            operation_key=f"recommendation:{run_id}:{resource}",
            identity=RecommendationIdentity(
                recommendation_id=recommendation_id,
                recommendation_version_id=version_id,
                run_id=run_id,
                resource_key=resource,
            ),
            evidence_snapshot_id=snapshot,
            rights_state=rights_evidence_state(analysis),
            assertion_sha256=assertion_sha256(analysis, ranking, priority, relationship),
            analysis=analysis,
            ranking_input=ranking,
            priority=priority,
            relationship=relationship,
            rationale=render_rationale(analysis.rationale_claims),
        )

        # Independent sessions race on exactly the same logical write.
        def commit(_):
            session = connect()
            try:
                return SnowflakeRecommendationRepository(session).save_recommendation(request)
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(commit, range(2)))
        assert results[0] == results[1]
        assert results[0].identity == request.identity
        assert results[0].evidence_observation_ids == (observation,)
        assert results[0].proposal_ids == (f"{version_id}:proposal:0",)
        assert repository.get_recommendation(request.operation_key) == results[0]
        assert repository.save_recommendation(request) == results[0]
        changed_relation = relationship.model_copy(update={"basis": "CONFLICTING_TEST_REPLAY"})
        conflict = request.model_copy(
            update={
                "relationship": changed_relation,
                "assertion_sha256": assertion_sha256(analysis, ranking, priority, changed_relation),
            }
        )
        try:
            repository.save_recommendation(conflict)
        except Exception as error:
            assert "CONFLICTING_OPERATION_REPLAY" in str(error), str(error)
        else:
            raise AssertionError("conflicting operation-key replay succeeded")
        final = repository.finalize_run(
            RunFinalizationReceipt(
                operation_key=f"finalize:{run_id}",
                run_id=run_id,
                status="SUCCEEDED_WITH_RECOMMENDATIONS",
                processed_count=1,
                recommendation_count=1,
            )
        )
        assert repository.get_finalization(run_id) == final
        persisted = one(
            connection,
            "SELECT COUNT(*), COUNT(DISTINCT recommendation_version_id) "
            "FROM DATASET_DISCOVERY.V_RECOMMENDATION_RECEIPTS WHERE operation_key = %s",
            (request.operation_key,),
        )
        assert persisted == (1, 1)
        print(
            {
                "run_id": run_id,
                "recommendation_version_id": version_id,
                "operation_key": request.operation_key,
                "concurrent_receipts_equal": True,
                "exact_replay": True,
                "conflicting_replay_denied": True,
                "lost_ack_receipt_recovered": True,
                "final_status": final.status,
                "logical_receipt_count": persisted[0],
            }
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
