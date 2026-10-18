"""Installed Snowflake acceptance cases; every statement is routed to fixed RI706 schemas."""

import json
from concurrent.futures import ThreadPoolExecutor

from run_release_integrity_fixture import BUNDLE, FROZEN, MARKER, OLD

from lyme_gap_atlas_data.release_completeness import tier1_eligibility_join


def require_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(label)


def run_matrix(f, migration, documents):
    owner, publisher, reader, runtime = (
        f.open(p) for p in ("owner", "publisher", "reader", "runtime")
    )

    def q(session, label, sql, params=()):
        return f.query(session, label, sql, params)

    def case(label, action):
        action()
        f.receipt["cases"].append({"case": label, "status": "PASS", "marker": MARKER})
        f.save()

    def fail(label, session, sql, params=(), *, text=None, permission=False):
        try:
            q(session, label, sql, params)
        except Exception as error:
            if permission:
                if (
                    getattr(error, "errno", None) not in {2003, 3001}
                    and getattr(error, "sqlstate", None) != "42501"
                ):
                    raise AssertionError(
                        label + " failed for a reason other than access denial"
                    ) from error
            elif text is None or text not in str(error):
                raise
        else:
            raise AssertionError(label + " did not fail closed")

    def pointer(release):
        q(
            migration,
            "fixture_pointer_only",
            "UPDATE PRESENTATION.SEMANTIC_RELEASE_POINTER "
            "SET current_release_id=%s WHERE pointer_key='ATLAS'",
            (release,),
        )
        migration.commit()

    def admit(decision, release=FROZEN, bundle=BUNDLE, session=owner):
        return q(
            session,
            "synthetic_admission",
            "CALL FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(%s,%s,%s,%s,%s)",
            ("tier1", release, bundle, decision, MARKER),
        )

    def tier1_count():
        return q(
            reader,
            "tier1_actual_eligibility",
            "SELECT COUNT(*),COUNT(DISTINCT v.county_fips) "
            "FROM PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V v"
            + tier1_eligibility_join()
            + (
                " WHERE (v.release_id=r_current.release_id AND v.bundle_sha256=r_c"
                "urrent.bundle_sha256) OR admission.artifact_id IS NOT NULL"
            ),
        )

    for view in ("CURRENT_RELEASE_V", "CURRENT_COUNTY_ATLAS_V", "CURRENT_TIER1_COUNTY_REVIEW_V"):
        q(
            migration,
            "fixture_reader_grant",
            "GRANT SELECT ON VIEW PRESENTATION." + view + " TO ROLE OH_LYME_DEV_READ",
        )
    pointer(OLD)
    case("tier1_exact", lambda: require_equal(tier1_count(), [(3144, 3144)], "tier1 exact"))
    pointer("synthetic-ri706-target")
    case("tier1_incompatible", lambda: require_equal(tier1_count(), [(0, 0)], "tier1 incompatible"))
    pointer(FROZEN)
    admit("synthetic-ri706-tier1-a")
    case(
        "tier1_compatible", lambda: require_equal(tier1_count(), [(3144, 3144)], "tier1 compatible")
    )
    admit("synthetic-ri706-tier1-a")
    admit("synthetic-ri706-tier1-b")
    case(
        "duplicate_admission_does_not_amplify",
        lambda: require_equal(tier1_count(), [(3144, 3144)], "duplicate admission amplified rows"),
    )
    case(
        "changed_admission_replay",
        lambda: fail(
            "changed_decision",
            owner,
            "CALL FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(%s,%s,%s,%s,%s)",
            ("tier1", FROZEN, BUNDLE, "synthetic-ri706-tier1-a", MARKER + " changed"),
            text="CHANGED_DECISION_REPLAY",
        ),
    )
    case(
        "wrong_release_binding",
        lambda: fail(
            "wrong_bundle",
            owner,
            "CALL FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(%s,%s,%s,%s,%s)",
            ("tier1", FROZEN, "f" * 64, "synthetic-wrong-bundle", MARKER),
            text="WRONG_RELEASE",
        ),
    )

    for table, column, replacement, expected_error in (
        ("SEMANTIC_COUNTY_ATLAS", "human_status", "changed", "CHANGED_MODEL_INPUT"),
        ("SEMANTIC_OBSERVATIONS", "source_row_hash", "changed", "CHANGED_OBSERVATION_LINEAGE"),
        ("SEMANTIC_DATA_SOURCES", "artifact_id", "changed", "CHANGED_SCIENTIFIC_LINEAGE"),
    ):
        # Own synthetic fixtures only; transactionally restore after each negative case.
        q(migration, "negative_begin", "BEGIN")
        q(
            migration,
            "negative_seed_change",
            "UPDATE PRESENTATION."
            + table
            + " SET "
            + column
            + "=%s WHERE release_id='synthetic-ri706-target'",
            (replacement,),
        )
        migration.commit()
        try:
            case(
                expected_error,
                lambda error=expected_error: fail(
                    "incompatible_lineage",
                    owner,
                    "CALL FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(%s,%s,%s,%s,%s)",
                    ("tier1", "synthetic-ri706-target", "a" * 64, "synthetic-negative", MARKER),
                    text=error,
                ),
            )
        finally:
            # Reconstruct from the unchanged original rows, without deleting history.
            if table == "SEMANTIC_COUNTY_ATLAS":
                q(
                    migration,
                    "restore_fixture_value",
                    "UPDATE PRESENTATION.SEMANTIC_COUNTY_ATLAS "
                    "SET human_status='Unknown' WHERE release_id='synthetic-ri706-target'",
                )
            elif table == "SEMANTIC_OBSERVATIONS":
                q(
                    migration,
                    "restore_fixture_hash",
                    (
                        "UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET source_row_hash=SHA"
                        "2(fips||source_key,256) WHERE release_id='synthetic-ri706-target'"
                    ),
                )
            else:
                q(
                    migration,
                    "restore_fixture_artifact",
                    "UPDATE PRESENTATION.SEMANTIC_DATA_SOURCES "
                    "SET artifact_id=source_key WHERE release_id='synthetic-ri706-target'",
                )
            migration.commit()

    # Separately authenticated roles must fail at access control, not input validation.
    for session, name in ((publisher, "publisher"), (reader, "reader"), (runtime, "runtime")):
        case(
            name + "_cannot_admit",
            lambda session=session: fail(
                "denied_admission",
                session,
                "CALL FEATURE_STORE.SP_ADMIT_MODEL_RELEASE('bad','bad','bad','bad','bad')",
                permission=True,
            ),
        )
    for session, name in ((reader, "reader"), (publisher, "publisher"), (runtime, "runtime")):
        case(
            name + "_private_table_denied",
            lambda session=session: fail(
                "denied_base",
                session,
                "SELECT * FROM FEATURE_STORE.SURVEILLANCE_SITUATION_AUTHORIZATIONS LIMIT 0",
                permission=True,
            ),
        )
        case(
            name + "_rollback_denied",
            lambda session=session: fail(
                "denied_rollback",
                session,
                (
                    "CALL FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(FALSE,'sy"
                    "nthetic only test')"
                ),
                permission=True,
            ),
        )

    authority = "synthetic-ri706-data-authorization"
    case(
        "missing_data_authority",
        lambda: fail(
            "no_authority",
            publisher,
            "CALL FEATURE_STORE.SP_STAGE_SURVEILLANCE_SITUATION_PART(%s,%s,0,'{}')",
            ("missing-synthetic-authority", "synthetic-ri706-missing"),
            text="DATA_PUBLICATION_AUTHORIZATION_REQUIRED",
        ),
    )
    q(
        owner,
        "synthetic_data_authorization",
        "CALL FEATURE_STORE.SP_AUTHORIZE_SURVEILLANCE_SITUATION_PUBLICATION(%s,%s,%s,%s,%s)",
        (authority, f.binding["commit"], f.binding["image_digest"], MARKER, MARKER),
    )
    payload = documents["outputs/138-surveillance-situation-batch-v1/county-assignments.json"]
    manifest = documents["config/models/138-surveillance-situation-batch-v1.json"]
    dictionary = documents["config/models/138-surveillance-situation-class-dictionary-v1.json"]
    approval = documents["config/models/138-surveillance-situation-batch-v1-approval.json"]
    attempt = "synthetic-ri706-frozen-v1"
    publish_sql = "CALL FEATURE_STORE.SP_PUBLISH_SURVEILLANCE_SITUATIONS(%s,%s,%s,%s,%s)"
    publish_params = (authority, attempt, manifest, dictionary, approval)
    original_parts = q(
        migration,
        "original_part_count",
        "SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_PARTS WHERE attempt_id=%s",
        (attempt,),
    )
    for index, start in enumerate(range(0, len(payload), 200000)):
        chunk = payload[start : start + 200000]
        q(
            publisher,
            "stage_frozen_part",
            "CALL FEATURE_STORE.SP_STAGE_SURVEILLANCE_SITUATION_PART(%s,%s,%s,%s)",
            (authority, attempt, index, chunk),
        )
        if index == 0 and original_parts == [(0,)]:
            case(
                "partial_staging_recoverable",
                lambda: fail(
                    "partial_publish",
                    publisher,
                    publish_sql,
                    publish_params,
                    text="COUNTY_DIGEST_MISMATCH",
                ),
            )
    q(
        publisher,
        "stage_identical_replay",
        "CALL FEATURE_STORE.SP_STAGE_SURVEILLANCE_SITUATION_PART(%s,%s,0,%s)",
        (authority, attempt, payload[:200000]),
    )
    case(
        "immutable_staging",
        lambda: fail(
            "changed_part",
            publisher,
            "CALL FEATURE_STORE.SP_STAGE_SURVEILLANCE_SITUATION_PART(%s,%s,0,'{}')",
            (authority, attempt),
            text="CHANGED_PART_REPLAY",
        ),
    )
    case(
        "changed_frozen_document",
        lambda: fail(
            "changed_manifest",
            publisher,
            publish_sql,
            (authority, attempt, manifest + " ", dictionary, approval),
            text="HANDOFF_DOCUMENT_DRIFT",
        ),
    )
    existing = q(
        migration,
        "batch_exists",
        "SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES",
    )
    if existing == [(0,)]:
        for index in range(7):
            q(
                publisher,
                "bounded_partial_attempt",
                "CALL FEATURE_STORE.SP_STAGE_SURVEILLANCE_SITUATION_PART(%s,%s,0,'{}')",
                (authority, "synthetic-ri706-unused-" + str(index)),
            )
        case(
            "ninth_attempt_denied",
            lambda: fail(
                "attempt_limit",
                publisher,
                "CALL FEATURE_STORE.SP_STAGE_SURVEILLANCE_SITUATION_PART(%s,%s,0,'{}')",
                (authority, "synthetic-ri706-ninth"),
                text="STAGING_ATTEMPT_LIMIT",
            ),
        )

        def atomic_state():
            return q(
                migration,
                "atomic_state",
                (
                    "SELECT batch_id,batch_version,revision,(SELECT COUNT(*) FROM FEAT"
                    "URE_STORE.SURVEILLANCE_SITUATION_EVENTS) FROM FEATURE_STORE.SURVE"
                    "ILLANCE_SITUATION_POINTER WHERE pointer_key='CURRENT'"
                ),
            )

        before_atomic = atomic_state()
        # Exercise a real failure after assignment INSERT, then prove no partial commit.
        q(
            migration,
            "break_fixture_geography",
            "CREATE OR REPLACE VIEW PRESENTATION.CURRENT_COUNTY_ATLAS_V "
            "AS SELECT * FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE FALSE",
        )
        try:
            case(
                "atomic_publication_failure",
                lambda: fail(
                    "geography_failure",
                    publisher,
                    publish_sql,
                    publish_params,
                    text="GEOGRAPHY_MISMATCH",
                ),
            )
            case(
                "assignment_insert_rolled_back",
                lambda: require_equal(
                    q(
                        migration,
                        "rollback_count",
                        "SELECT COUNT(*) FROM FEATURE_STORE.COUNTY_SURVEILLANCE_SITUATIONS",
                    ),
                    [(0,)],
                    "partial assignment commit",
                ),
            )
            case(
                "batch_insert_rolled_back",
                lambda: require_equal(
                    q(
                        migration,
                        "rollback_batch_count",
                        "SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES",
                    ),
                    [(0,)],
                    "partial batch commit",
                ),
            )
            case(
                "pointer_and_events_rolled_back",
                lambda: require_equal(
                    atomic_state(), before_atomic, "partial pointer/event commit"
                ),
            )
        finally:
            q(
                migration,
                "restore_fixture_geography",
                (
                    "CREATE OR REPLACE VIEW PRESENTATION.CURRENT_COUNTY_ATLAS_V AS SEL"
                    "ECT c.* FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS c JOIN PRESENTATI"
                    "ON.CURRENT_RELEASE_V r ON c.release_id=r.release_id"
                ),
            )
    q(publisher, "publish_frozen_fits", publish_sql, publish_params)
    q(
        owner,
        "synthetic_restore_active_baseline",
        "CALL FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(TRUE,%s)",
        (MARKER,),
    )
    expected = [
        ("surveillance-situation-four-state", 3144, 3144),
        ("surveillance-situation-tick-pathogen", 3144, 3144),
    ]
    case(
        "both_frozen_fits",
        lambda: require_equal(
            q(
                reader,
                "fit_counts",
                (
                    "SELECT model_id,COUNT(*),COUNT(DISTINCT county_fips) FROM PRESENT"
                    "ATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V GROUP BY model_id "
                    "ORDER BY model_id"
                ),
            ),
            expected,
            "fit coverage",
        ),
    )
    case(
        "four_probabilities_each",
        lambda: require_equal(
            q(
                reader,
                "probability_integrity",
                (
                    "SELECT COUNT(*) FROM (SELECT model_id,county_fips,COUNT(*) AS n,S"
                    "UM(p.value:probability::DOUBLE) AS total FROM PRESENTATION.CURREN"
                    "T_COUNTY_SURVEILLANCE_SITUATIONS_V s,LATERAL FLATTEN(INPUT=>s.pro"
                    "babilities) p GROUP BY model_id,county_fips) WHERE n<>4 OR ABS(to"
                    "tal-1)>1e-6"
                ),
            ),
            [(0,)],
            "probability integrity",
        ),
    )
    models = json.loads(payload)["models"]
    from collections import Counter

    expected_classes = sorted(
        (m["model_id"], key, count)
        for m in models
        for key, count in Counter(r["class_id"] for r in m["rows"]).items()
    )
    case(
        "scientific_class_distributions",
        lambda: require_equal(
            q(
                reader,
                "class_counts",
                (
                    "SELECT model_id,class_id,COUNT(*) FROM PRESENTATION.CURRENT_COUNT"
                    "Y_SURVEILLANCE_SITUATIONS_V GROUP BY model_id,class_id ORDER BY m"
                    "odel_id,class_id"
                ),
            ),
            expected_classes,
            "class counts",
        ),
    )
    q(
        owner,
        "synthetic_deactivation",
        "CALL FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(FALSE,%s)",
        (MARKER,),
    )
    q(publisher, "publish_does_not_reactivate", publish_sql, publish_params)
    case(
        "replay_respects_withdrawal",
        lambda: require_equal(
            q(
                reader,
                "withdrawn_count",
                "SELECT COUNT(*) FROM PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V",
            ),
            [(0,)],
            "withdrawal replay",
        ),
    )
    q(
        owner,
        "synthetic_reactivation",
        "CALL FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(TRUE,%s)",
        (MARKER,),
    )
    pointer("synthetic-ri706-target")
    case(
        "incompatible_fit_unavailable",
        lambda: require_equal(
            q(
                reader,
                "incompatible_fit_count",
                "SELECT COUNT(*) FROM PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V",
            ),
            [(0,)],
            "incompatible fit",
        ),
    )
    case(
        "incompatible_activation_denied",
        lambda: fail(
            "incompatible_activation",
            owner,
            "CALL FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(TRUE,%s)",
            (MARKER,),
            text="NO_COMPATIBLE_APPROVED_BATCH",
        ),
    )
    pointer(FROZEN)

    def concurrent(profile, sql, params):
        sessions = [f.open(profile), f.open(profile)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(q, session, "concurrent_" + profile, sql, params)
                for session in sessions
            ]
            for index, future in enumerate(futures):
                try:
                    future.result(timeout=90)
                except Exception as error:
                    # A bounded lock conflict is retried only with the identical artifact.
                    if getattr(error, "sqlstate", None) not in {"40001", "57014"}:
                        raise
                    q(sessions[index], "concurrent_exact_retry", sql, params)

    case(
        "concurrent_publication_replay",
        lambda: concurrent("publisher", publish_sql, publish_params),
    )
    case(
        "concurrent_admission",
        lambda: concurrent(
            "owner",
            "CALL FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(%s,%s,%s,%s,%s)",
            ("tier1", FROZEN, BUNDLE, "synthetic-ri706-concurrent", MARKER),
        ),
    )
    case(
        "one_concurrent_decision",
        lambda: require_equal(
            q(
                migration,
                "concurrent_decision_count",
                (
                    "SELECT COUNT(*) FROM FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY WH"
                    "ERE decision_id='synthetic-ri706-concurrent'"
                ),
            ),
            [(1,)],
            "duplicate concurrent decision",
        ),
    )
    case(
        "final_publication_membership",
        lambda: require_equal(
            q(
                reader,
                "final_fit_counts",
                (
                    "SELECT model_id,COUNT(*),COUNT(DISTINCT county_fips) FROM PRESENT"
                    "ATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V GROUP BY model_id "
                    "ORDER BY model_id"
                ),
            ),
            expected,
            "final counts",
        ),
    )
    f.receipt["frozen_county_sha256"] = (
        "02b62d7a4cb8970b3cd2506f5206a386a9ceed7cb2253baea16299be2d06ec9b"
    )
    f.receipt["synthetic_only_not_compatibility_approval"] = True
    from release_integrity_fixture_inventory import run_inventory_matrix

    run_inventory_matrix(f, migration, owner)
