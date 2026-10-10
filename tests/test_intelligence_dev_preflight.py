import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "feed_preflight", Path(__file__).parents[1] / "scripts/verify_intelligence_dev_preflight.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture(autouse=True)
def synthetic_reviewed_artifact_policy(monkeypatch):
    monkeypatch.setattr(
        module,
        "REVIEWED_RESTRICTED_ARTIFACT_POLICIES",
        {source_id: "SYNTHETIC_REVIEWED" for source_id in module.SOURCE_ENDPOINTS},
    )


def synthetic_registry_case(source_id="cdc-eid-expedited"):
    source = json.loads(
        (Path(__file__).parent / "fixtures/intelligence/v1/candidate-source.json").read_text()
    )
    endpoint = module.SOURCE_ENDPOINTS[source_id]
    source.update(
        source_id=source_id,
        fetch_location=endpoint,
        canonical_location=endpoint,
        approved_hosts=[endpoint.split("/")[2]],
        state="active",
        topics=[],
        geographies=[],
        trust_classification="official_public_health",
    )
    source["cadence"].update(poll_seconds=86400)
    source["limits"].update(maximum_bytes=2097152, maximum_items=250, timeout_seconds=30)
    for key in ("approval", "trust_review"):
        source[key].update(
            status="approved",
            decision_ref="synthetic-technical-review",
            reviewed_at="2026-10-03T03:06:52Z",
            owner="synthetic-delegated-reviewer",
        )
    source["access_use"].update(
        terms_location="https://www.cdc.gov/other/agencymaterials.html",
        availability_verified_at="2026-10-03T03:06:52Z",
        content_retention_policy_ref="synthetic-longterm",
    )
    checksum = module.identity_hash(source)
    receipt = {
        "source_id": source_id,
        "registry_version": source["registry_version"],
        "source_sha256": checksum,
        "decision_ref": "synthetic-technical-review",
        "raw_policy_ref": "intelligence-raw-30d-v1",
        "retention_policy_ref": "synthetic-longterm",
        "artifact_policy": "SYNTHETIC_REVIEWED",
        "native_policy": {
            "policy_ref": "synthetic-native-review",
            "source_sha256": checksum,
            "inventory": ["item/title", "item/link", "item/pubDate"],
            "permitted_paths": ["item/title", "item/link", "item/pubDate"],
            "required_paths": [],
            "published_path": "item/pubDate",
            "published_format": "rfc822",
            "updated_path": None,
        },
    }
    return source, receipt


def registry_row(source):
    return {
        "SOURCE_ID": source["source_id"],
        "REGISTRY_VERSION": source["registry_version"],
        "REGISTRY_SHA256": module.identity_hash(source),
        "SOURCE_DOCUMENT_JSON": json.dumps(source),
    }


@pytest.mark.parametrize("source_id", module.SOURCE_ENDPOINTS)
def test_exact_reviewed_registry_proof_is_boolean_and_redacted(source_id):
    source, receipt = synthetic_registry_case(source_id)
    result = module.source_result(source_id, [registry_row(source)], [receipt])
    assert result == {
        "source_id": source_id,
        "passed": True,
        "exact_reviewed_source_matches": True,
        "reason": "PASS",
    }
    assert source["approval"]["owner"] not in json.dumps(result)
    assert receipt["source_sha256"] not in json.dumps(result)
    assert "registry_version" not in result


@pytest.mark.parametrize(
    "key,bad,reason",
    [
        ("SOURCE_ID", "private-source", "SOURCE_ID_MISMATCH"),
        ("REGISTRY_VERSION", 99, "VERSION_MISMATCH"),
        ("REGISTRY_VERSION", True, "VERSION_MISMATCH"),
        ("REGISTRY_SHA256", "0" * 64, "HASH_MISMATCH"),
        ("SOURCE_DOCUMENT_JSON", "{", "INVALID_DOCUMENT"),
        ("SOURCE_DOCUMENT_JSON", '{"source_id":"a","source_id":"b"}', "INVALID_DOCUMENT"),
        ("SOURCE_DOCUMENT_JSON", "x" * 65537, "OVERSIZED_OR_MISSING_DOCUMENT"),
        ("SOURCE_DOCUMENT_JSON", None, "OVERSIZED_OR_MISSING_DOCUMENT"),
    ],
    ids=lambda value: "oversized" if isinstance(value, str) and len(value) > 128 else None,
)
def test_invalid_registry_row_fails_with_fixed_reason(key, bad, reason):
    source, receipt = synthetic_registry_case()
    row = registry_row(source)
    row[key] = bad
    assert module.source_result(source["source_id"], [row], [receipt])["reason"] == reason


@pytest.mark.parametrize(
    "field,key,bad,reason",
    [
        (None, "fetch_location", "https://wwwnc.cdc.gov/wrong.xml", "ENDPOINT_MISMATCH"),
        (None, "approved_hosts", ["private.example"], "HOST_MISMATCH"),
        ("cadence", "poll_seconds", 3600, "CADENCE_MISMATCH"),
        ("limits", "maximum_items", 5000, "LIMITS_MISMATCH"),
        (None, "topics", ["tick-borne"], "INFERRED_CLASSIFICATION"),
        ("approval", "status", "pending", "INVALID_DOCUMENT"),
        ("access_use", "public_excerpt_permitted", True, "RIGHTS_OR_AVAILABILITY_MISMATCH"),
        ("access_use", "availability_verified_at", None, "INVALID_DOCUMENT"),
        ("trust_review", "decision_ref", "unreviewed-reference", "REVIEWED_CANDIDATE_MISMATCH"),
        (
            "access_use",
            "content_retention_policy_ref",
            "unreviewed-policy",
            "REVIEWED_CANDIDATE_MISMATCH",
        ),
    ],
)
def test_source_semantics_and_exact_review_bindings(field, key, bad, reason):
    source, receipt = synthetic_registry_case()
    target = source[field] if field else source
    target[key] = bad
    assert (
        module.source_result(source["source_id"], [registry_row(source)], [receipt])["reason"]
        == reason
    )


def test_absent_duplicate_unreviewed_and_receipt_policy_mismatch():
    source, receipt = synthetic_registry_case()
    sid = source["source_id"]
    row = registry_row(source)
    assert module.source_result(sid, [], [receipt])["reason"] == "ABSENT"
    assert module.source_result(sid, [row, row], [receipt])["reason"] == "DUPLICATE_LATEST"
    assert module.source_result(sid, [row], [])["reason"] == "REVIEWED_CANDIDATE_REQUIRED"
    for key, value, expected in [
        ("decision_ref", "wrong-review", "REVIEW_REFERENCE_MISMATCH"),
        ("raw_policy_ref", "PUBLIC_SEVEN_YEAR", "RETENTION_MISMATCH"),
        ("retention_policy_ref", "wrong-policy", "RETENTION_MISMATCH"),
    ]:
        changed = copy.deepcopy(receipt)
        changed[key] = value
        assert module.source_result(sid, [row], [changed])["reason"] == expected
    changed = copy.deepcopy(receipt)
    changed["native_policy"]["permitted_paths"].append("item/description")
    assert module.source_result(sid, [row], [changed])["reason"] == "NATIVE_POLICY_MISMATCH"


@pytest.mark.parametrize(
    "bad",
    [
        False,
        True,
        None,
        0,
        [],
        {},
        ["SYNTHETIC_REVIEWED"],
        "",
        "PUBLIC_SEVEN_YEAR",
        "arbitrary-policy",
    ],
)
def test_artifact_policy_requires_exact_reviewed_restricted_string(bad):
    source, receipt = synthetic_registry_case()
    receipt["artifact_policy"] = bad
    assert (
        module.source_result(source["source_id"], [registry_row(source)], [receipt])["reason"]
        == "ARTIFACT_POLICY_MISMATCH"
    )


def test_unadmitted_artifact_policy_stays_blocked(monkeypatch):
    source, receipt = synthetic_registry_case()
    monkeypatch.setattr(module, "REVIEWED_RESTRICTED_ARTIFACT_POLICIES", {})
    assert (
        module.source_result(source["source_id"], [registry_row(source)], [receipt])["reason"]
        == "ARTIFACT_POLICY_REVIEW_REQUIRED"
    )


@pytest.mark.parametrize("bad", ["PUBLIC_SEVEN_YEAR", " ", " bad-policy ", False, []])
def test_invalid_reviewed_policy_identifier_cannot_authorize_artifact(monkeypatch, bad):
    source, receipt = synthetic_registry_case()
    receipt["artifact_policy"] = bad
    monkeypatch.setattr(module, "REVIEWED_RESTRICTED_ARTIFACT_POLICIES", {source["source_id"]: bad})
    assert (
        module.source_result(source["source_id"], [registry_row(source)], [receipt])["reason"]
        == "ARTIFACT_POLICY_REVIEW_REQUIRED"
    )


@pytest.mark.parametrize("bad", [None, "UNKNOWN", "FALSE", "", 0, {}, []])
def test_grant_option_missing_or_unrecognized_never_passes(bad):
    row = {
        "grantee_name": "OH_LYME_DEV_RUNTIME",
        "granted_to": "ROLE",
        "privilege": "INSERT",
        "grant_option": bad,
    }
    result = module.privileges_match("INTELLIGENCE_RAW_RETENTION_AUDIT", [row])
    assert not result["grant_option_metadata_valid"]
    assert not result["required_privileges_present"]
    assert not result["target_role_privileges_exact"]
    assert result["target_role_grant_option_present"]


def test_fixed_registry_reads_distinguish_absent_denied_and_preserve_safe_progress(capsys):
    class RegistryCursor(Cursor):
        def execute(self, sql, **kwargs):
            super().execute(sql, **kwargs)
            assert kwargs["timeout"] == 10
            assert "LIMIT 2" in sql and "DENSE_RANK" in sql
            assert not any(word in sql for word in ("INSERT", "UPDATE", "GRANT", "CREATE"))
            if "nih-news-releases" in sql:
                raise PermissionError("private-document-and-reviewer")

    cursor = RegistryCursor(None)
    report = {}
    module.inspect_sources(cursor, report, [])
    assert [r["reason"] for r in report["sources"]] == ["ABSENT", "UNKNOWN_QUERY_FAILED"]
    assert not report["source_prerequisites_passed"]
    assert "private-document-and-reviewer" not in capsys.readouterr().out


def test_wrong_identity_cannot_reach_registry_with_receipts():
    cursor = Cursor((module.USER, "ACCOUNTADMIN", module.DEV, module.WAREHOUSE))
    with pytest.raises(ValueError, match="IDENTITY"):
        module.inspect(cursor, {}, receipts=[])
    assert len(cursor.sql) == 2


def test_registry_proof_precedes_object_describe_denial_with_nih_blocked(capsys):
    source, receipt = synthetic_registry_case()
    row = registry_row(source)

    class DeniedObject(Cursor):
        def execute(self, sql, **kwargs):
            super().execute(sql, **kwargs)
            if "nih-news-releases" in sql:
                raise PermissionError("private NIH detail")
            if "AS source_document_json" in sql:
                self.description = [(key,) for key in row]
            elif sql.startswith("SHOW"):
                self.description = [("name",), ("owner",)]
            elif sql.startswith("DESCRIBE"):
                assert len([s for s in self.sql if "AS source_document_json" in s]) == 2
                raise PermissionError("private object detail")

        def fetchall(self):
            if "AS source_document_json" in self.sql[-1]:
                return [tuple(row.values())]
            return [("INTELLIGENCE_RAW_RETENTION_DOCUMENTS", module.ROLE)]

    report = {}
    cursor = DeniedObject((module.USER, module.ROLE, module.DEV, module.WAREHOUSE))
    with pytest.raises(PermissionError):
        module.inspect(cursor, report, receipts=[receipt])
    assert report["sources"][0]["passed"]
    assert report["sources"][1]["reason"] == "UNKNOWN_QUERY_FAILED"
    assert not report["objects"][0]["inspection_complete"]
    output = capsys.readouterr().out
    assert "private" not in output and receipt["source_sha256"] not in output
    assert source["approval"]["owner"] not in output


def test_main_deadline_starts_before_connection_and_timeout_is_redacted(
    monkeypatch, tmp_path, capsys
):
    events = []

    class Timer:
        daemon = False

        def __init__(self, seconds, callback):
            assert seconds == 50
            self.callback = callback

        def start(self):
            events.append("watchdog_started")

        def cancel(self):
            events.append("watchdog_cancelled")

    def timed_out(settings):
        assert events == ["watchdog_started"]
        raise TimeoutError("private timeout account/document")

    receipts = tmp_path / "reviewed.json"
    receipts.write_text('{"receipts":[]}')
    monkeypatch.setenv("FEED_PREFLIGHT_ACCOUNTING_CONFIRMED", "true")
    monkeypatch.setattr(module, "RECEIPTS", receipts)
    monkeypatch.setattr(module.threading, "Timer", Timer)
    monkeypatch.setattr(module, "connect", timed_out)
    with pytest.raises(SystemExit, match="FEED_PREFLIGHT_FAILED"):
        module.main()
    output = capsys.readouterr().out
    assert "DIAGNOSTIC_FAILED" in output and "private" not in output
    assert events == ["watchdog_started", "watchdog_cancelled"]


@pytest.mark.parametrize(
    "table",
    [
        "INTELLIGENCE_RAW_RETENTION_DOCUMENTS",
        "INTELLIGENCE_RAW_RETENTION_AUDIT",
        "INTELLIGENCE_SOURCE_VERSIONS",
    ],
)
def test_approved_ddl_timestamp_not_null_matches_and_nullable_drift_fails(table):
    root = Path(__file__).parents[1]
    ddl_path = (
        next((root / "migrations").glob("V135*.sql"))
        if table == "INTELLIGENCE_SOURCE_VERSIONS"
        else root / "docs/contracts/intelligence/v2/dev-minimum-access-reviewed.sql"
    )
    ddl = ddl_path.read_text(encoding="utf-8")
    body = re.search(
        rf"CREATE TABLE(?: IF NOT EXISTS)? GOVERNANCE\.{table} \((.*?)\n\);",
        ddl,
        re.S | re.I,
    )
    assert body is not None
    # Generate DESCRIBE rows from the approved DDL, not diagnostic expectations.
    columns = []
    for name, kind, not_null, default in re.findall(
        r"^\s*(\w+)\s+(VARCHAR\(\d+\)|NUMBER|VARIANT|TIMESTAMP_TZ|TIMESTAMP_LTZ)"
        r"(\s+NOT NULL)?(?:\s+DEFAULT (CURRENT_TIMESTAMP\(\)))?[,]?\s*$",
        body[1],
        re.M | re.I,
    ):
        kind = kind.upper()
        kind = {
            "NUMBER": "NUMBER(38,0)",
            "TIMESTAMP_TZ": "TIMESTAMP_TZ(9)",
            "TIMESTAMP_LTZ": "TIMESTAMP_LTZ(9)",
        }.get(kind, kind)
        columns.append(
            {
                "name": name.upper(),
                "type": kind,
                "kind": "COLUMN",
                "null?": "N" if not_null else "Y",
                "default": default or None,
            }
        )
    timestamp = next(row for row in columns if row["name"] in {"REGISTERED_AT", "RECORDED_AT"})
    assert timestamp["null?"] == "N"
    assert module.table_matches(table, columns)
    timestamp["null?"] = "Y"
    assert not module.table_matches(table, columns)


def test_budget_requires_public_safe_confirmation_only():
    for value in ("false", "", '{"spent_usd":0}'):
        with pytest.raises(ValueError, match="CONFIRMATION_REQUIRED"):
            module.budget(value)
    assert module.budget("true") is None


class Cursor:
    def __init__(self, identity):
        self.identity = identity
        self.sql = []
        self.description = [("name",), ("owner",)]

    def execute(self, sql, **kwargs):
        self.sql.append(sql)

    def fetchone(self):
        return self.identity

    def fetchall(self):
        return []


def test_wrong_identity_stops_before_object_inspection():
    cursor = Cursor((module.USER, "ACCOUNTADMIN", module.DEV, module.WAREHOUSE))
    with pytest.raises(ValueError, match="IDENTITY"):
        module.inspect(cursor, {})
    assert len(cursor.sql) == 2


def test_hidden_objects_remain_unknown_no_registry_records():
    cursor = Cursor((module.USER, module.ROLE, module.DEV, module.WAREHOUSE))
    report = {}
    module.inspect(cursor, report)
    assert len(report["objects"]) == 5
    assert all(item["state"] == "NOT_VISIBLE_NOT_PROOF_OF_ABSENCE" for item in report["objects"])
    assert len(cursor.sql) == 10
    assert all(
        item["direct_describe_succeeded"] is False
        for item in report["objects"]
        if item["target"] in module.DIRECT_PROBE_TARGETS
    )
    assert not any("registry_sha256" in sql or "registry_document" in sql for sql in cursor.sql)


def test_exact_direct_describe_can_prove_existence_without_a_show_row():
    class DirectlyVisible(Cursor):
        def execute(self, sql, **kwargs):
            super().execute(sql, **kwargs)
            if sql.startswith("DESCRIBE"):
                self.description = [("name",)]

        def fetchall(self):
            if self.sql[-1].startswith("DESCRIBE"):
                return [("EXISTS",)]
            return []

    cursor = DirectlyVisible((module.USER, module.ROLE, module.DEV, module.WAREHOUSE))
    report = {}
    module.inspect(cursor, report)
    assert all(
        item["state"] == "EXISTS_BUT_NOT_LISTED"
        for item in report["objects"]
        if item["target"] in module.DIRECT_PROBE_TARGETS
    )
    assert not report["object_prerequisites_passed"]  # Owner and grants remain unverified.


def test_partial_completed_safe_observations_survive_later_failure():
    class Failing(Cursor):
        def execute(self, sql, **kwargs):
            super().execute(sql, **kwargs)
            if "INTELLIGENCE_RAW_RETENTION_AUDIT" in sql:
                raise RuntimeError("private failure text")

    cursor = Failing((module.USER, module.ROLE, module.DEV, module.WAREHOUSE))
    report = {}
    with pytest.raises(RuntimeError):
        module.inspect(cursor, report)
    assert len(report["objects"]) == 1
    assert report["objects"][0]["inspection_complete"] is True
    assert "private failure" not in str(report)


def test_workflow_public_safe_input_and_exit_before_migration():
    workflow = (Path(__file__).parents[1] / ".github/workflows/deploy-dev.yml").read_text()
    branch = workflow.index('if [ "$DIAGNOSE_INTELLIGENCE_DEV" = "true" ]')
    execute = workflow.index("uv run python scripts/verify_intelligence_dev_preflight.py", branch)
    assert workflow.index("exit 0", execute) < workflow.index("SELECT CURRENT_ACCOUNT()")
    for private_surface in (
        "BUDGET_JSON",
        "PUBLIC_KEY",
        "upload-artifact",
        "spent_usd",
        "evidence_ref",
    ):
        assert private_surface not in workflow


def test_definition_comparison_detects_version_and_private_projection_changes():
    source = (
        Path(__file__).parents[1] / "docs/contracts/intelligence/v2/presentation-projection.sql"
    ).read_text()
    start = source.index("CREATE VIEW IF NOT EXISTS PRESENTATION.INTELLIGENCE_FEED_V2")
    ddl = source[start:].split(";", 1)[0]
    assert module.view_matches("INTELLIGENCE_FEED_V2", ddl)
    assert not module.view_matches("INTELLIGENCE_FEED_V2", ddl.replace("'2.0.0'", "'1.0.0'"))
    assert not module.view_matches(
        "INTELLIGENCE_FEED_V2",
        ddl.replace(
            "OBJECT_CONSTRUCT() AS derived_metadata", "c.item_document AS derived_metadata"
        ),
    )


def test_watchdog_exit_is_unconditional_when_evidence_output_fails(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("output failed")

    class Exited(BaseException):
        pass

    exits = []

    def leave(code):
        exits.append(code)
        raise Exited

    monkeypatch.setattr("builtins.print", broken)
    monkeypatch.setattr(module.os, "_exit", leave)
    with pytest.raises(Exited):
        module.terminate({"objects": []})
    assert exits == [124]


def test_catalog_and_owner_status_survive_describe_denial():
    class Denied(Cursor):
        def fetchall(self):
            return [("INTELLIGENCE_RAW_RETENTION_DOCUMENTS", module.ROLE)]

        def execute(self, sql, **kwargs):
            super().execute(sql, **kwargs)
            if sql.startswith("DESCRIBE"):
                raise PermissionError("private details")

    report = {}
    cursor = Denied((module.USER, module.ROLE, module.DEV, module.WAREHOUSE))
    with pytest.raises(PermissionError):
        module.inspect(cursor, report)
    assert report["identity_matches_expected"] is True
    observed = report["objects"][0]
    assert observed["state"] == "VISIBLE"
    assert observed["owner_matches_expected"] is True
    assert observed["inspection_complete"] is False
    assert module.ROLE not in str(report)


def test_table_reuse_requires_exact_columns_types_nullability_and_defaults():
    name = "INTELLIGENCE_RAW_RETENTION_DOCUMENTS"
    columns = [
        {
            "name": column,
            "type": kind,
            "kind": "COLUMN",
            "null?": "Y" if nullable else "N",
            "default": default or None,
        }
        for column, kind, nullable, default in module.TABLE_SHAPES[name]
    ]
    assert module.table_matches(name, columns)
    assert not module.table_matches(
        name,
        columns + [{"name": "PRIVATE_BODY", "type": "VARIANT", "kind": "COLUMN", "null?": "Y"}],
    )
    for key, wrong in (("type", "VARCHAR(1024)"), ("null?", "Y"), ("default", "'invented'")):
        changed = [dict(row) for row in columns]
        changed[0][key] = wrong
        assert not module.table_matches(name, changed)


def test_three_approved_scopes_reject_extra_runtime_access_and_grant_option():
    for name in (
        "INTELLIGENCE_RAW_RETENTION_DOCUMENTS",
        "INTELLIGENCE_RAW_RETENTION_AUDIT",
        "INTELLIGENCE_FEED_V2",
    ):
        role, privileges = module.ROLE_PRIVILEGES[name]
        grants = [
            {
                "grantee_name": role,
                "granted_to": "ROLE",
                "privilege": privilege,
                "grant_option": "false",
            }
            for privilege in privileges
        ]
        assert module.privileges_match(name, grants)["target_role_privileges_exact"] is True
        assert module.privileges_match(name, [])["required_privileges_present"] is False
        changed = grants + [
            {
                "grantee_name": role,
                "granted_to": "ROLE",
                "privilege": "DELETE",
                "grant_option": "false",
            }
        ]
        assert module.privileges_match(name, changed)["unexpected_target_role_privileges"] is True
        changed = [dict(row, grant_option="true") for row in grants]
        assert module.privileges_match(name, changed)["target_role_grant_option_present"] is True


@pytest.mark.parametrize("column_index", [0, -1])
@pytest.mark.parametrize("field", ["name", "type", "kind", "null?", "default"])
def test_table_shape_rejects_missing_metadata_even_for_no_default(column_index, field):
    name = "INTELLIGENCE_RAW_RETENTION_DOCUMENTS"
    columns = [
        {
            "name": column,
            "type": kind,
            "kind": "COLUMN",
            "null?": "Y" if nullable else "N",
            "default": default or None,
        }
        for column, kind, nullable, default in module.TABLE_SHAPES[name]
    ]
    del columns[column_index][field]
    assert not module.table_matches(name, columns)


@pytest.mark.parametrize("flag", [None, "", "UNKNOWN", "n", False, 0])
@pytest.mark.parametrize("column_index", [0, -1])
def test_table_shape_rejects_unknown_nullability_for_required_and_nullable_columns(
    flag, column_index
):
    name = "INTELLIGENCE_RAW_RETENTION_DOCUMENTS"
    columns = [
        {
            "name": column,
            "type": kind,
            "kind": "COLUMN",
            "null?": "Y" if nullable else "N",
            "default": default or None,
        }
        for column, kind, nullable, default in module.TABLE_SHAPES[name]
    ]
    columns[column_index]["null?"] = flag
    assert not module.table_matches(name, columns)


def test_table_shape_preserves_exact_identifier_case_and_explicit_null_default():
    name = "INTELLIGENCE_RAW_RETENTION_DOCUMENTS"
    columns = [
        {
            "name": column,
            "type": kind,
            "kind": "COLUMN",
            "null?": "Y" if nullable else "N",
            "default": default or None,
        }
        for column, kind, nullable, default in module.TABLE_SHAPES[name]
    ]
    assert columns[0]["default"] is None
    assert module.table_matches(name, columns)
    columns[0]["name"] = columns[0]["name"].lower()
    assert not module.table_matches(name, columns)


@pytest.mark.parametrize("default", [False, 0, {}, []])
def test_table_shape_rejects_non_string_default_metadata(default):
    name = "INTELLIGENCE_RAW_RETENTION_DOCUMENTS"
    columns = [
        {
            "name": column,
            "type": kind,
            "kind": "COLUMN",
            "null?": "Y" if nullable else "N",
            "default": default or None,
        }
        for column, kind, nullable, default in module.TABLE_SHAPES[name]
    ]
    columns[0]["default"] = default
    assert not module.table_matches(name, columns)
