"""Immutable artifact identity and deterministic object-key generation."""

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    sha256: str
    byte_count: int
    object_key: str


def create_artifact(
    *, payload: bytes, environment: str, resource_key: str, run_id: str
) -> Artifact:
    digest = hashlib.sha256(payload).hexdigest()
    key = f"{environment}/{resource_key}/{run_id}/{digest}.bin"
    return Artifact(sha256=digest, byte_count=len(payload), object_key=key)
