"""Protected pair installs preserve every unrelated pending/applied migration."""

from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data import migrations

PARENTS = {"V141", "V149", "V151", "V152", "V155", "V156"}
COMMIT = "a" * 40


def setup_plan(monkeypatch, *, resumed=False, missing_parent=False, wrong_receipt=False):
    plan = [
        m
        for m in migrations.load_migrations()
        if m.version in PARENTS | {"V150", "V154", "V157", "V158"}
    ]
    applied = [
        (m.version, m.sha256)
        for m in plan
        if m.version in PARENTS and not (missing_parent and m.version == "V141")
    ]
    target = next(m for m in plan if m.version == "V157")
    if resumed:
        applied.append((target.version, target.sha256))
    reviewed = [
        migrations._migration_metadata(m)
        for m in plan
        if m.version not in dict(applied) or (resumed and m.version == "V157")
    ]
    monkeypatch.setattr(migrations, "load_migrations", lambda: plan)
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *_: {})
    monkeypatch.setattr(migrations, "_migration_settings", lambda settings, *_: settings)
    cursor = Mock()
    if resumed:
        cursor.fetchall.side_effect = [
            applied,
            [(target.filename, target.sha256, "b" * 40 if wrong_receipt else COMMIT)],
        ]
    else:
        cursor.fetchall.return_value = applied
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    return connection, reviewed


@pytest.mark.parametrize("resumed", [False, True])
def test_only_new_pair_executes_and_unrelated_pending_remain(monkeypatch, resumed):
    connection, reviewed = setup_plan(monkeypatch, resumed=resumed)
    assert migrations.apply_migrations(
        Mock(),
        migrations.PROD_DATABASE,
        COMMIT,
        expected_pending=reviewed,
        release_integrity_only=True,
    ) == (["V158"] if resumed else ["V157", "V158"])
    statements = [call.args[0] for call in connection.execute_string.call_args_list]
    assert len(statements) == (1 if resumed else 2)
    assert all("CREATE TABLE IF NOT EXISTS FEATURE_STORE." in sql for sql in statements)
    assert not any(
        "CREATE OR REPLACE VIEW PRESENTATION.CURRENT_CLIMATE" in sql for sql in statements
    )
    assert not any("CREATE OR REPLACE VIEW PRESENTATION.CURRENT_TIER1" in sql for sql in statements)


@pytest.mark.parametrize("kind", ["missing_parent", "wrong_receipt", "wrong_checksum"])
def test_invalid_scope_or_receipt_stops_before_ddl(monkeypatch, kind):
    connection, reviewed = setup_plan(
        monkeypatch,
        resumed=kind == "wrong_receipt",
        missing_parent=kind == "missing_parent",
        wrong_receipt=kind == "wrong_receipt",
    )
    if kind == "wrong_checksum":
        reviewed[-1] = reviewed[-1] | {"sha256": "b" * 64}
    with pytest.raises((ValueError, PermissionError)):
        migrations.apply_migrations(
            Mock(),
            migrations.PROD_DATABASE,
            COMMIT,
            expected_pending=reviewed,
            release_integrity_only=True,
        )
    connection.execute_string.assert_not_called()


@pytest.mark.parametrize(
    "database,reviewed,extra",
    [
        (migrations.DEV_DATABASE, [], {}),
        (migrations.PROD_DATABASE, None, {}),
        (migrations.PROD_DATABASE, [], {"cdc_admission_only": True}),
    ],
)
def test_scope_rejects_ambiguous_authority_before_connect(monkeypatch, database, reviewed, extra):
    connect = Mock()
    monkeypatch.setattr(migrations, "connect", connect)
    with pytest.raises(PermissionError):
        migrations.apply_migrations(
            Mock(),
            database,
            COMMIT,
            expected_pending=reviewed,
            release_integrity_only=True,
            **extra,
        )
    connect.assert_not_called()


def test_prior_cdc_operator_reviews_but_defers_the_new_pair(monkeypatch):
    wanted = {"V149", "V150", "V155", "V156", "V157", "V158"}
    plan = [m for m in migrations.load_migrations() if m.version in wanted]
    applied = [(m.version, m.sha256) for m in plan if m.version in {"V149", "V155"}]
    monkeypatch.setattr(migrations, "load_migrations", lambda: plan)
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *_: {})
    monkeypatch.setattr(migrations, "_migration_settings", lambda settings, *_: settings)
    cursor = Mock()
    cursor.fetchall.return_value = applied
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    reviewed = [migrations._migration_metadata(m) for m in plan if m.version not in dict(applied)]
    assert migrations.apply_migrations(
        Mock(), migrations.PROD_DATABASE, COMMIT, expected_pending=reviewed, cdc_admission_only=True
    ) == ["V156"]
    assert connection.execute_string.call_count == 1
