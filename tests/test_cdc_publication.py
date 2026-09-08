from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from lyme_gap_atlas_data import cdc_publication
from lyme_gap_atlas_data.cdc_policy import snapshot_checksum


def publication_connection(
    monkeypatch: pytest.MonkeyPatch, *, failed: int = 0, unchanged: bool = False
) -> MagicMock:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.rowcount = 1
    cursor.fetchall.side_effect = [[("a" * 64,)], [("run", f"rule-{i}", 0, 0) for i in range(8)]]
    checksum = snapshot_checksum(["a" * 64]) if unchanged else "old"
    cursor.fetchone.side_effect = [(1,), (8, failed), (2, checksum, "old-run"), (0,)]
    monkeypatch.setattr(cdc_publication, "connect", lambda _: connection)
    return connection


def test_unchanged_snapshot_does_not_write_rows_or_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = publication_connection(monkeypatch, unchanged=True)
    result = cdc_publication.publish_snapshot(
        "source", "new-run", "validation", "lease", expected_revision=2
    )
    assert result["status"] == "UNCHANGED"
    statements = [
        call.args[0]
        for call in connection.cursor.return_value.__enter__.return_value.execute.call_args_list
    ]
    assert not any("INSERT" in statement for statement in statements)
    assert not any("UPDATE GOVERNANCE.CDC_PUBLICATIONS" in statement for statement in statements)


def test_failed_quality_keeps_previous_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = publication_connection(monkeypatch, failed=1)
    with pytest.raises(ValueError, match="passing quality"):
        cdc_publication.publish_snapshot(
            "source", "new-run", "validation", "lease", expected_revision=2
        )
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()


def test_snapshot_write_error_rolls_back_pointer_and_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = publication_connection(monkeypatch)
    cursor = connection.cursor.return_value.__enter__.return_value

    def execute(statement: str, *_args: object) -> None:
        if "UPDATE GOVERNANCE.CDC_PUBLICATIONS" in statement:
            raise RuntimeError("write failure")

    cursor.execute.side_effect = execute
    with pytest.raises(RuntimeError, match="write failure"):
        cdc_publication.publish_snapshot(
            "source", "new-run", "validation", "lease", expected_revision=2
        )
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()


def test_changed_snapshot_copies_before_pointer_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = publication_connection(monkeypatch)
    result = cdc_publication.publish_snapshot(
        "source", "new-run", "validation", "lease", expected_revision=2
    )
    assert result["status"] == "PUBLISHED"
    statements = [
        c.args[0]
        for c in connection.cursor.return_value.__enter__.return_value.execute.call_args_list
    ]
    copy = next(i for i, sql in enumerate(statements) if "INSERT INTO CONFORMED" in sql)
    pointer = next(
        i for i, sql in enumerate(statements) if "UPDATE GOVERNANCE.CDC_PUBLICATIONS" in sql
    )
    assert copy < pointer
    connection.commit.assert_called_once()


def test_stale_revision_cannot_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = publication_connection(monkeypatch)
    with pytest.raises(ValueError, match="Publication changed"):
        cdc_publication.publish_snapshot(
            "source", "new-run", "validation", "lease", expected_revision=1
        )
    connection.rollback.assert_called_once()


def test_candidate_changed_between_validation_and_copy_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = publication_connection(monkeypatch)
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [("a" * 64,)],
        [("run", f"rule-{i}", 0, int(i == 7)) for i in range(8)],
    ]
    with pytest.raises(ValueError, match="transactional quality"):
        cdc_publication.publish_snapshot(
            "source", "new-run", "validation", "lease", expected_revision=2
        )
    assert not any(
        "UPDATE GOVERNANCE.CDC_PUBLICATIONS" in c.args[0] for c in cursor.execute.call_args_list
    )
    connection.rollback.assert_called_once()


@pytest.mark.parametrize("snapshot,retained", [(None, None), (("validation", 5), (4,))])
def test_rollback_rejects_missing_or_incomplete_snapshot(
    monkeypatch: pytest.MonkeyPatch, snapshot: object, retained: object
) -> None:
    connection = publication_connection(monkeypatch)
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [snapshot, retained]
    monkeypatch.setattr(cdc_publication, "cdc_operation", lambda: nullcontext("lease"))
    publish = MagicMock()
    monkeypatch.setattr(cdc_publication, "publish_snapshot", publish)
    with pytest.raises(ValueError):
        cdc_publication.rollback_publication("source", "old-run", expected_revision=2)
    publish.assert_not_called()


def test_rollback_uses_original_validation_and_atomic_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = publication_connection(monkeypatch)
    connection.cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        ("validation", 5),
        (5,),
    ]
    monkeypatch.setattr(cdc_publication, "cdc_operation", lambda: nullcontext("lease"))
    publish = MagicMock(return_value={"status": "PUBLISHED"})
    monkeypatch.setattr(cdc_publication, "publish_snapshot", publish)
    cdc_publication.rollback_publication("source", "old-run", expected_revision=2)
    publish.assert_called_once_with(
        "source",
        "old-run",
        "validation",
        "lease",
        expected_revision=2,
        candidate_relation="CONFORMED.CDC_VALIDATED_SNAPSHOTS",
        reason="OPERATOR_ROLLBACK",
    )
