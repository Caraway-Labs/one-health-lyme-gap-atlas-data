"""Stable, run-scoped identities for retained acquisition members."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .adapters import AcquisitionArtifact


@dataclass(frozen=True)
class ArtifactMember:
    ingestion_run_id: str
    name: str
    role: str
    artifact_id: str
    source_uri: str
    media_type: str
    sha256: str
    byte_count: int
    artifact_uri: str | None = None
    row_count: int | None = None

    @property
    def member_id(self) -> str:
        return hashlib.sha256(self.name.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingestion_run_id": self.ingestion_run_id,
            "member_id": self.member_id,
            "name": self.name,
            "role": self.role,
            "artifact_id": self.artifact_id,
            "source_uri": self.source_uri,
            "media_type": self.media_type,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "artifact_uri": self.artifact_uri,
            "row_count": self.row_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ArtifactMember:
        member = cls(
            ingestion_run_id=str(value["ingestion_run_id"]),
            name=str(value["name"]),
            role=str(value["role"]),
            artifact_id=str(value["artifact_id"]),
            source_uri=str(value["source_uri"]),
            media_type=str(value["media_type"]),
            sha256=str(value["sha256"]),
            byte_count=int(value["byte_count"]),
            artifact_uri=str(value["artifact_uri"]) if value.get("artifact_uri") else None,
            row_count=int(value["row_count"]) if value.get("row_count") is not None else None,
        )
        if value.get("member_id") != member.member_id:
            raise ValueError("Artifact member identity mismatch")
        validate_members((member,))
        return member


def validate_names(artifacts: Iterable[AcquisitionArtifact]) -> None:
    names: set[str] = set()
    for artifact in artifacts:
        if not artifact.name or not re.fullmatch(r"[^\\/\x00-\x1f]{1,256}", artifact.name):
            raise ValueError("Invalid acquisition artifact member name")
        if artifact.name in names:
            raise ValueError("Duplicate acquisition artifact member name")
        names.add(artifact.name)


def validate_members(members: Iterable[ArtifactMember]) -> tuple[ArtifactMember, ...]:
    result = tuple(members)
    names: set[str] = set()
    ids: set[str] = set()
    for member in result:
        if not member.name or not re.fullmatch(r"[^\\/\x00-\x1f]{1,256}", member.name):
            raise ValueError("Invalid artifact member name")
        if member.name in names or member.member_id in ids:
            raise ValueError("Duplicate artifact member identity")
        if not member.role or not member.artifact_id or not member.ingestion_run_id:
            raise ValueError("Artifact member lineage is incomplete")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", member.sha256)
            or member.byte_count < 0
            or (member.row_count is not None and member.row_count < 0)
        ):
            raise ValueError("Invalid artifact member checksum or byte count")
        names.add(member.name)
        ids.add(member.member_id)
    return tuple(sorted(result, key=lambda item: item.name))


def resolve_member(
    members: Iterable[ArtifactMember], *, name: str | None = None, role: str | None = None
) -> ArtifactMember:
    if name is None and role is None:
        raise ValueError("Artifact member name or role is required")
    found = [
        member
        for member in validate_members(members)
        if (name is None or member.name == name) and (role is None or member.role == role)
    ]
    if len(found) != 1:
        raise ValueError("Artifact member is missing or ambiguous")
    return found[0]
