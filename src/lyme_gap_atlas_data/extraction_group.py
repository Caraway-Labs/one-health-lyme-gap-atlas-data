"""Bounded group identity; continuation stays closed until canary proof is wired."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


class GroupGateBlocked(RuntimeError):
    """Safe, typed failure before claim or provider construction."""

    def __init__(self, capability: str) -> None:
        self.capability = capability
        self.report = {
            "status": "BLOCKED",
            "stage": "group_gate",
            "capability": capability,
            "failure_category": "group_contract",
            "retryable": False,
            "remediation_owner": "literature_operation_owner",
            "next_action": "review_group_inventory_and_required_canary_evidence",
        }
        super().__init__(json.dumps(self.report, sort_keys=True))


@dataclass(frozen=True)
class ExtractionGroup:
    group_id: str
    discovery_run_id: str
    pmids: tuple[str, ...]
    image_digest: str
    configuration_version: str

    @property
    def inventory_sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.pmids, separators=(",", ":")).encode()).hexdigest()

    def context(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "discovery_run_id": self.discovery_run_id,
            "pmids": list(self.pmids),
            "inventory_sha256": self.inventory_sha256,
            "image_digest": self.image_digest,
            "configuration_version": self.configuration_version,
            "group_contract_version": 1,
            "phase": "canary",
        }

    @classmethod
    def parse(
        cls,
        raw: str,
        *,
        discovery_run_id: str | None,
        image_digest: str | None,
        configuration_version: str,
    ) -> ExtractionGroup:
        try:
            if len(raw) > 8192:
                raise ValueError
            manifest = json.loads(raw, object_pairs_hook=_unique_object)
            expected = {
                "group_id",
                "discovery_run_id",
                "pmids",
                "image_digest",
                "configuration_version",
                "group_contract_version",
                "phase",
            }
            if not isinstance(manifest, dict) or set(manifest) != expected:
                raise ValueError
            if (
                type(manifest["group_contract_version"]) is not int
                or manifest["group_contract_version"] != 1
            ):
                raise ValueError
            group_id = str(uuid.UUID(manifest["group_id"]))
            scope_id = str(uuid.UUID(manifest["discovery_run_id"]))
            pmids = manifest["pmids"]
            if (
                not isinstance(pmids, list)
                or not 10 <= len(pmids) <= 25
                or any(
                    not isinstance(pmid, str) or not re.fullmatch(r"[1-9][0-9]{0,8}", pmid)
                    for pmid in pmids
                )
                or len(set(pmids)) != len(pmids)
                or not isinstance(manifest["image_digest"], str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["image_digest"])
                or not isinstance(manifest["configuration_version"], str)
                or manifest["phase"] not in ("canary", "continue")
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise GroupGateBlocked("valid_bounded_group_manifest") from None
        if (
            scope_id != discovery_run_id
            or manifest["image_digest"] != image_digest
            or manifest["configuration_version"] != configuration_version
        ):
            raise GroupGateBlocked("matching_group_runtime_identity")
        if manifest["phase"] == "continue":
            # Do not accept caller-supplied assertions as authoritative receipts.
            raise GroupGateBlocked("fresh_canary_receipts_and_serving_visibility_not_implemented")
        return cls(group_id, scope_id, tuple(sorted(pmids)), image_digest, configuration_version)
