"""PubMed/PMC/Neo4j resumable work-queue primitives (#230)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .types import FailureCategory


class LiteratureStage(StrEnum):
    DISCOVERY = "DISCOVERY"
    METADATA = "METADATA"
    PMCID_OA_ADMIT = "PMCID_OA_ADMIT"
    JATS_ACQUIRE = "JATS_ACQUIRE"
    EXTRACT = "EXTRACT"
    CONTRIBUTION_VALIDATE = "CONTRIBUTION_VALIDATE"
    GRAPH_STAGE = "GRAPH_STAGE"
    PUBLISH = "PUBLISH"


class LiteratureItemStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXCEPTION_REVIEW = "EXCEPTION_REVIEW"
    SKIPPED = "SKIPPED"


DEFAULT_LITERATURE_STAGES: tuple[LiteratureStage, ...] = tuple(LiteratureStage)


@dataclass
class LiteratureStageState:
    stage: LiteratureStage
    status: LiteratureItemStatus = LiteratureItemStatus.PENDING
    attempt_count: int = 0
    artifact_ref: str | None = None
    failure_category: FailureCategory | None = None
    next_action: str | None = None


@dataclass
class LiteratureWorkItem:
    work_item_id: str
    pmid: str
    stages: list[LiteratureStageState] = field(default_factory=list)
    license_exception: bool = False

    def __post_init__(self) -> None:
        if not self.stages:
            self.stages = [LiteratureStageState(stage=stage) for stage in DEFAULT_LITERATURE_STAGES]

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "pmid": self.pmid,
            "license_exception": self.license_exception,
            "stages": [
                {
                    "stage": item.stage.value,
                    "status": item.status.value,
                    "attempt_count": item.attempt_count,
                    "artifact_ref": item.artifact_ref,
                    "failure_category": (
                        item.failure_category.value if item.failure_category else None
                    ),
                    "next_action": item.next_action,
                }
                for item in self.stages
            ],
        }


class LiteratureWorkQueue:
    """In-process durable-stage simulator; Snowflake persistence lands with migration."""

    def __init__(self) -> None:
        self._items: dict[str, LiteratureWorkItem] = {}

    def enqueue(self, work_item_id: str, pmid: str) -> LiteratureWorkItem:
        item = LiteratureWorkItem(work_item_id=work_item_id, pmid=pmid)
        self._items[work_item_id] = item
        return item

    def get(self, work_item_id: str) -> LiteratureWorkItem:
        return self._items[work_item_id]

    def advance(
        self,
        work_item_id: str,
        *,
        fail_at: LiteratureStage | None = None,
        license_ambiguous: bool = False,
    ) -> LiteratureWorkItem:
        item = self.get(work_item_id)
        if license_ambiguous:
            item.license_exception = True
            for stage in item.stages:
                if stage.stage is LiteratureStage.PMCID_OA_ADMIT:
                    stage.status = LiteratureItemStatus.EXCEPTION_REVIEW
                    stage.failure_category = FailureCategory.POLICY_LICENSE
                    stage.next_action = "exception_queue"
                    break
            return item

        for stage in item.stages:
            if stage.status is LiteratureItemStatus.COMPLETED:
                continue
            stage.status = LiteratureItemStatus.RUNNING
            stage.attempt_count += 1
            if fail_at is not None and stage.stage is fail_at:
                stage.status = LiteratureItemStatus.FAILED
                if fail_at is LiteratureStage.EXTRACT:
                    stage.failure_category = FailureCategory.PROVIDER_MODEL
                    stage.next_action = "retry:EXTRACT"
                elif fail_at is LiteratureStage.PUBLISH:
                    stage.failure_category = FailureCategory.GRAPH
                    stage.next_action = "retry:PUBLISH"
                else:
                    stage.failure_category = FailureCategory.ACQUISITION
                    stage.next_action = f"retry:{fail_at.value}"
                return item
            stage.status = LiteratureItemStatus.COMPLETED
            stage.artifact_ref = f"{item.pmid}:{stage.stage.value}"
            stage.next_action = None
        return item

    def retry_stage(self, work_item_id: str, stage: LiteratureStage) -> LiteratureWorkItem:
        item = self.get(work_item_id)
        target = next(item_stage for item_stage in item.stages if item_stage.stage is stage)
        if target.status not in {
            LiteratureItemStatus.FAILED,
            LiteratureItemStatus.EXCEPTION_REVIEW,
        }:
            return item
        # Independent retry: do not reset completed upstream stages.
        for upstream in item.stages:
            if upstream.stage is stage:
                break
            if upstream.status is not LiteratureItemStatus.COMPLETED:
                raise RuntimeError("Cannot retry stage before upstream completion")
        target.status = LiteratureItemStatus.PENDING
        target.failure_category = None
        target.next_action = None
        return self.advance(work_item_id)
