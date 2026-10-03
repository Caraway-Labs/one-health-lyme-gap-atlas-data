"""Feed-scoped guards on the existing checkpoint implementations.

Scientific checkpoint classes and their retention policies remain unchanged.
These subclasses preserve each underlying store's supported runtime protocols.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..intelligence_raw_runtime import FeedRawRetention, buffer_namespace
from ..intelligence_retention import CopyKind
from .artifact_replay import ArtifactMember, resolve_member
from .checkpoints import FileCheckpointStore, InMemoryCheckpointStore, SnowflakeCheckpointStore


class IntelligenceMemoryCheckpoints(InMemoryCheckpointStore):
    def __init__(self, retention: FeedRawRetention) -> None:
        super().__init__()
        self.feed_retention = retention
        self.namespace = buffer_namespace("memory")

    def _locator(self, run_id: str, suffix: str) -> str:
        return f"{self.namespace}/{run_id}/{suffix}"

    def save_payload(self, run_id: str, payload: object) -> None:
        self.feed_retention.bind(run_id, payload)
        self.feed_retention.register_buffer(
            self._locator(run_id, "payload"), lambda: self._payloads.pop(run_id, None) is not None
        )
        with self.feed_retention.copy_access(
            run_id, "checkpoint_payload", self._locator(run_id, "payload"), write=True
        ):
            super().save_payload(run_id, payload)

    def load_payload(self, run_id: str) -> object | None:
        if run_id not in self._payloads:
            return None
        with self.feed_retention.copy_access(
            run_id, "checkpoint_payload", self._locator(run_id, "payload")
        ):
            return super().load_payload(run_id)

    def save_binary_artifact(self, run_id: str, content: bytes, sha256: str) -> None:
        self.feed_retention.register_buffer(
            self._locator(run_id, "binary"), lambda: self._binary.pop(run_id, None) is not None
        )
        with self.feed_retention.copy_access(
            run_id, "binary_replay", self._locator(run_id, "binary"), write=True
        ):
            super().save_binary_artifact(run_id, content, sha256)

    def load_binary_artifact(self, run_id: str) -> bytes | None:
        if run_id not in self._binary:
            return None
        with self.feed_retention.copy_access(
            run_id, "binary_replay", self._locator(run_id, "binary")
        ):
            return super().load_binary_artifact(run_id)

    def save_artifact_member(self, member: ArtifactMember, content: bytes) -> None:
        self.feed_retention.register_buffer(
            self._locator(member.ingestion_run_id, member.name),
            lambda: (
                self._members.get(member.ingestion_run_id, {}).pop(member.name, None) is not None
            ),
        )
        with self.feed_retention.copy_access(
            member.ingestion_run_id,
            "artifact_member",
            self._locator(member.ingestion_run_id, member.name),
            write=True,
        ):
            super().save_artifact_member(member, content)

    def load_artifact_member(
        self, run_id: str, *, name: str | None = None, role: str | None = None
    ) -> bytes:
        member = resolve_member(self.list_artifact_members(run_id), name=name, role=role)
        with self.feed_retention.copy_access(
            run_id, "artifact_member", self._locator(run_id, member.name)
        ):
            return super().load_artifact_member(run_id, name=name, role=role)


class IntelligenceFileCheckpoints(FileCheckpointStore):
    def __init__(self, root: Any, retention: FeedRawRetention) -> None:
        super().__init__(root)
        self.feed_retention = retention

    def _write_raw(self, run_id: str, kind: CopyKind, path: Path, content: bytes) -> None:
        # Both final and staging paths are durable claims before any bytes.
        # A hard crash can leave the staging path: exact cleanup can find it.
        temporary = path.with_name(path.name + f".raw-{uuid4().hex}.tmp")
        self.feed_retention.reserve_copy(run_id, kind, temporary.resolve().as_uri())
        with self.feed_retention.copy_access(run_id, kind, path.resolve().as_uri(), write=True):
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)

    def save_payload(self, run_id: str, payload: object) -> None:
        self.feed_retention.bind(run_id, payload)
        path = self._payload_path(run_id, "payload")
        content = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        self._write_raw(run_id, "local_checkpoint", path, content)

    def load_payload(self, run_id: str) -> object | None:
        path = self._payload_path(run_id, "payload")
        if not path.exists():
            return None
        with self.feed_retention.copy_access(run_id, "local_checkpoint", path.resolve().as_uri()):
            return super().load_payload(run_id)

    def save_binary_artifact(self, run_id: str, content: bytes, sha256: str) -> None:
        import hashlib

        if hashlib.sha256(content).hexdigest() != sha256:
            raise ValueError("Binary artifact checksum mismatch")
        path = self._binary_path(run_id)
        if path.exists():
            if self.load_binary_artifact(run_id) != content:
                raise ValueError("Binary artifact checkpoint mismatch")
            return
        self._write_raw(run_id, "binary_replay", path, content)
        self._write_json(self._payload_path(run_id, "artifact-meta"), {"sha256": sha256})

    def load_binary_artifact(self, run_id: str) -> bytes | None:
        path = self._binary_path(run_id)
        if not path.exists():
            return None
        with self.feed_retention.copy_access(run_id, "binary_replay", path.resolve().as_uri()):
            return super().load_binary_artifact(run_id)

    def save_artifact_member(self, member: ArtifactMember, content: bytes) -> None:
        import hashlib

        if (
            hashlib.sha256(content).hexdigest() != member.sha256
            or len(content) != member.byte_count
        ):
            raise ValueError("Artifact member checksum mismatch")
        path, metadata = self._member_paths(member)
        if path.exists() or metadata.exists():
            if not path.exists() or not metadata.exists():
                raise ValueError("Artifact member checkpoint incomplete")
            if ArtifactMember.from_dict(json.loads(metadata.read_text())) != member:
                raise ValueError("Artifact member checkpoint mismatch")
            if self.load_artifact_member(member.ingestion_run_id, name=member.name) != content:
                raise ValueError("Artifact member checkpoint mismatch")
            return
        self._write_raw(member.ingestion_run_id, "artifact_member", path, content)
        self._write_json(metadata, member.to_dict())

    def load_artifact_member(
        self, run_id: str, *, name: str | None = None, role: str | None = None
    ) -> bytes:
        member = resolve_member(self.list_artifact_members(run_id), name=name, role=role)
        path, _ = self._member_paths(member)
        with self.feed_retention.copy_access(run_id, "artifact_member", path.resolve().as_uri()):
            return super().load_artifact_member(run_id, name=name, role=role)


class IntelligenceSnowflakeCheckpoints(SnowflakeCheckpointStore):
    def __init__(self, retention: FeedRawRetention, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.feed_retention = retention
        self._unvalidated_factory = self._connection_factory
        self._connection_factory = self._checked_factory

    @contextmanager
    def _checked_factory(self) -> Iterator[Any]:
        with self._unvalidated_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_TRANSACTION()")
                if cursor.fetchall() != [
                    (
                        f"OH_LYME_{self.feed_retention.environment}_RUNTIME",
                        f"ONE_HEALTH_LYME_GAP_ATLAS_{self.feed_retention.environment}",
                        None,
                    )
                ]:
                    raise PermissionError("INTELLIGENCE_RAW_WRITER_CONTEXT_REQUIRED")
            yield connection

    def _payload_locator(self, run_id: str) -> str:
        return f"snowflake://ONE_HEALTH_LYME_GAP_ATLAS_{self.feed_retention.environment}/GOVERNANCE/INGESTION_RUN_PAYLOADS/{run_id}"

    def save_payload(self, run_id: str, payload: object) -> None:
        self.feed_retention.bind(run_id, payload)
        with self.feed_retention.copy_access(
            run_id, "checkpoint_payload", self._payload_locator(run_id), write=True
        ):
            super().save_payload(run_id, payload)

    def load_payload(self, run_id: str) -> object | None:
        # Metadata guard precedes the first SELECT of XML-bearing VARIANT.
        with self.feed_retention.copy_access(
            run_id, "checkpoint_payload", self._payload_locator(run_id)
        ):
            return super().load_payload(run_id)

    def load_source_artifact(self, run_id: str) -> bytes | None:
        self.feed_retention.require_run(run_id)
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT artifact_uri, sha256 FROM GOVERNANCE.RAW_ARTIFACTS
                WHERE ingestion_run_id=%s AND artifact_type='SOURCE_PAYLOAD'
                QUALIFY COUNT(*) OVER () = 1""",
                (run_id,),
            )
            artifact = cursor.fetchone()
        if artifact is None:
            return None
        with self.feed_retention.copy_access(run_id, "raw_object", str(artifact[0])):
            return self._read_spaces_artifact(str(artifact[0]), str(artifact[1]))

    def load_artifact_member(
        self, run_id: str, *, name: str | None = None, role: str | None = None
    ) -> bytes:
        self.feed_retention.require_run(run_id)
        member = resolve_member(self.list_artifact_members(run_id), name=name, role=role)
        if member.artifact_uri is None:
            raise PermissionError("INTELLIGENCE_RAW_CLAIM_REQUIRED")
        with self.feed_retention.copy_access(run_id, "raw_object", member.artifact_uri):
            return super().load_artifact_member(run_id, name=name, role=role)
