import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data import climate_manifest_prep as prep
from lyme_gap_atlas_data import climate_release, sql_sessions


def packet() -> dict:
    return json.loads(
        Path("docs/contracts/climate/january-2025-recorded-metadata-candidate.json").read_text()
    )


def spec() -> dict:
    return json.loads(
        Path("docs/contracts/climate/january-2025-dev-release-input.json").read_text()
    )


def test_preparation_uses_bounded_sql_session(monkeypatch: pytest.MonkeyPatch) -> None:
    assert prep.connect is sql_sessions.connect
    connection = Mock()
    connection.cursor.return_value.__enter__ = Mock(return_value=connection.cursor.return_value)
    connection.cursor.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(sql_sessions, "shared_connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", "60")
    assert prep.connect(Mock()) is connection
    connection.cursor.return_value.execute.assert_called_once_with(
        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=60, "
        "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=10, ABORT_DETACHED_QUERY=TRUE, "
        "QUERY_TAG='DATA594_BOUNDED_COHORT_DELIVERY'"
    )


def annual() -> dict:
    value = json.loads(
        Path("docs/contracts/semantic-release/governed-2026-09-15-manifest.json").read_text()
    )
    value["release_id"] = spec()["annual_release_id"]
    return value


def cursor_for(annual_manifest: dict) -> Mock:
    cursor = Mock()
    cursor.fetchone.side_effect = [
        (*prep.OPERATOR, prep.DEV_DATABASE, "OH_LYME_DEV_INGEST_XS_WH"),
        (1560, 2, 0, 1559),
    ]
    cursor.fetchall.return_value = [
        (
            spec()["annual_release_id"],
            "PUBLISHED",
            spec()["annual_bundle_sha256"],
            annual_manifest,
        )
    ]
    return cursor


def test_prepares_release_from_bound_annual_and_retained_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prep, "ROW_COUNT", 2)
    monkeypatch.setattr(climate_release, "ROW_COUNT", 2)
    monkeypatch.setattr(prep, "reconstruct_capture_ids", lambda *_: ["a" * 64, "b" * 64])
    selected = spec()
    selected["row_count"] = 2
    result = prep.prepare(
        cursor_for(annual()),
        selected,
        packet(),
        review_commit="a" * 40,
        review_url="https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/657#pullrequestreview-123",
        reviewer="Independent reviewer",
    )
    assert result["release_id"] == selected["release_id"]
    assert result["sources"] == annual()["sources"]
    assert result["climate_extension"]["capture_ids"] == ["a" * 64, "b" * 64]
    assert result["climate_extension"]["capture_membership_sha256"] == prep.MEMBERSHIP_SHA


def test_rejects_changed_annual_binding_before_membership_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = Mock()
    monkeypatch.setattr(prep, "reconstruct_capture_ids", called)
    cursor = cursor_for(annual())
    cursor.fetchall.return_value = [(spec()["annual_release_id"], "PUBLISHED", "0" * 64, annual())]
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_ANNUAL_RELEASE_BINDING"):
        prep.prepare(
            cursor,
            spec(),
            packet(),
            review_commit="a" * 40,
            review_url="https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/657#pullrequestreview-123",
            reviewer="Independent reviewer",
        )
    called.assert_not_called()


def test_review_must_match_merged_checkout_and_exact_reviewed_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_commit = "b" * 40
    reviewed_commit = "a" * 40
    review_url = (
        "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/"
        "pull/657#pullrequestreview-123"
    )
    clean_review = (
        f"Independent read-only review of exact head {reviewed_commit}: no material findings."
    )
    pull = {
        "number": 657,
        "merged_at": "2026-10-09T00:00:00Z",
        "merge_commit_sha": release_commit,
        "base": {"ref": "main"},
        "head": {"sha": reviewed_commit},
    }
    reviews = [
        {
            "commit_id": reviewed_commit,
            "state": "COMMENTED",
            "body": clean_review,
            "submitted_at": "2026-10-09T00:00:00Z",
            "user": {"login": "CarawayLabs"},
            "html_url": review_url,
        }
    ]

    def open_review(request, timeout):  # type: ignore[no-untyped-def]
        assert timeout == 10
        payload = reviews if request.full_url.endswith("/reviews?per_page=100") else pull
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(prep, "urlopen", open_review)
    monkeypatch.setattr(
        prep.subprocess,
        "run",
        lambda args, **_kwargs: SimpleNamespace(
            returncode=0
            if args == ["git", "merge-base", "--is-ancestor", release_commit, release_commit]
            else 1
        ),
    )
    assert prep.verified_review("fixture-token", release_commit) == {
        "commit": reviewed_commit,
        "url": review_url,
        "reviewer": "CarawayLabs",
    }
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_REVIEW_RELEASE_BINDING"):
        prep.verified_review("fixture-token", "c" * 40)
    pull["merge_commit_sha"] = "d" * 40
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_REVIEW_RELEASE_BINDING"):
        prep.verified_review("fixture-token", release_commit)
    monkeypatch.setattr(
        prep.subprocess,
        "run",
        lambda _args, **_kwargs: SimpleNamespace(returncode=0),
    )
    assert prep.verified_review("fixture-token", release_commit)["commit"] == reviewed_commit
    pull["merge_commit_sha"] = release_commit
    reviews[0]["commit_id"] = "c" * 40
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_REVIEW_RECORD"):
        prep.verified_review("fixture-token", release_commit)
    reviews[0]["commit_id"] = reviewed_commit
    reviews[0]["body"] = "P1: unresolved release defect"
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_REVIEW_RECORD"):
        prep.verified_review("fixture-token", release_commit)
    reviews[-1]["body"] = clean_review
    reviews[-1]["state"] = "CHANGES_REQUESTED"
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_REVIEW_RECORD"):
        prep.verified_review("fixture-token", release_commit)
    reviews[-1]["state"] = "COMMENTED"
    reviews[-1]["body"] = clean_review + " P1: release evidence invalid."
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_REVIEW_RECORD"):
        prep.verified_review("fixture-token", release_commit)
    reviews[-1]["body"] = clean_review + " [P1] release evidence invalid."
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_REVIEW_RECORD"):
        prep.verified_review("fixture-token", release_commit)
    reviews[0]["body"] = clean_review
    reviews.append(
        {
            **reviews[0],
            "submitted_at": "2026-10-10T00:00:00Z",
            "body": "P1: new unresolved release defect",
        }
    )
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_REVIEW_RECORD"):
        prep.verified_review("fixture-token", release_commit)
