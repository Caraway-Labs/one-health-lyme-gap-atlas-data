"""Offline error-preservation and unchanged deployment-boundary checks."""

import base64
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote, quote_plus

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "daily_prose", ROOT / "scripts/deploy_intelligence_daily.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
RID = "c3041e18-5aa5-4b2c-bbc5-9ef53bc828d0"
ENVELOPE = f'PUT https://api.digitalocean.com/v2/apps/example: 400 (request "{RID}") '
PROSE = "App spec image reconciliation requires an explicit component source binding before update."


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_useful_unknown_error_meaning_survives_in_full(channel):
    detail = ENVELOPE + PROSE
    stdout = json.dumps({"errors": [{"detail": detail}]}) if channel == "stdout" else ""
    stderr = detail if channel == "stderr" else ""
    result = m.validation_metadata(stderr, stdout)
    assert result["redacted_messages"] == [PROSE]
    assert result["status"] == "400" and result["request_id"] == RID
    assert not result["root_cause_established"]
    assert "OTHER" not in json.dumps(result)


def test_each_channel_json_decoded_once_and_error_not_duplicated():
    stdout = json.dumps({"errors": [{"detail": ENVELOPE + PROSE}]})
    original = m.json.loads
    with patch.object(m.json, "loads", wraps=original) as decode:
        message = m.update_failure("", stdout)
    assert decode.call_count == 1
    assert message.count(PROSE) == 1


SECRET = "p@ss word/\\\nΩ-sensitive-canary"


@pytest.mark.parametrize(
    "encoded",
    [
        SECRET,
        json.dumps(SECRET)[1:-1],
        json.dumps(json.dumps(SECRET)[1:-1])[1:-1],
        json.dumps(SECRET, ensure_ascii=False)[1:-1].replace("/", "\\/"),
        quote(SECRET, safe=""),
        quote_plus(SECRET, safe=""),
        quote(quote(SECRET, safe=""), safe=""),
        base64.b64encode(SECRET.encode()).decode(),
        base64.urlsafe_b64encode(SECRET.encode()).decode().rstrip("="),
    ],
)
def test_encoded_known_secret_removed_before_any_truncation(encoded):
    prose = 'invalid credential value "' + encoded + '"; component source binding is required.'
    result = m.validation_metadata(
        "", json.dumps({"errors": [{"detail": ENVELOPE + prose}]}), [SECRET]
    )
    safe = json.dumps(result)
    assert encoded not in "\n".join(result["redacted_messages"])
    assert "sensitive-canary" not in safe
    assert "component source binding is required." in safe


@pytest.mark.parametrize(
    "value",
    [
        "dop_v1_" + "a" * 64,
        "ghp_" + "b" * 36,
        "github_pat_" + "c" * 50,
        "AKIA" + "D" * 16,
        "EV[opaque-provider-reference]",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturecanary00",
    ],
)
def test_credential_patterns_are_defensively_redacted(value):
    result = m.validation_metadata(ENVELOPE + "invalid credential " + value)
    assert value not in json.dumps(result)


@pytest.mark.parametrize(
    "value",
    [
        'SNOWFLAKE_PRIVATE_KEY_B64="unlisted-credential-canary"',
        "Authorization: Bearer unlisted-credential-canary",
        "password='unlisted-credential-canary'",
        "registry_credentials=unlisted-credential-canary",
        "https://user:unlisted-credential-canary@registry.example/image",
        "-----BEGIN PRIVATE KEY-----\nunlisted-credential-canary\n-----END PRIVATE KEY-----",
    ],
)
def test_header_assignment_pem_and_url_credentials_are_not_logged(value):
    result = m.validation_metadata(ENVELOPE + "invalid access: " + value)
    assert "unlisted-credential-canary" not in json.dumps(result)


def test_redaction_precedes_length_bound_and_indicates_truncation():
    secret = "near-boundary-secret-canary"
    detail = ENVELOPE + "x" * (m.MAX_ERROR_MESSAGE - 6) + secret + " end"
    result = m.validation_metadata("", json.dumps({"errors": [{"detail": detail}]}), [secret])
    assert result["truncated"]
    assert len(result["redacted_messages"][0]) <= m.MAX_ERROR_MESSAGE
    assert "near-boundary" not in json.dumps(result)


def test_total_output_bound_multiple_errors_and_oversized_input():
    output = json.dumps({"errors": [{"detail": "x" * 3000} for _ in range(16)]})
    result = m.validation_metadata("", output)
    assert sum(map(len, result["redacted_messages"])) <= m.MAX_ERROR_TOTAL
    assert result["truncated"]
    assert (
        "oversized" in m.validation_metadata("z" * (m.MAX_ERROR_INPUT + 1))["redacted_messages"][0]
    )


@pytest.mark.parametrize(
    "value",
    [
        '{"spec":{"jobs":[{"envs":[]}]}}',
        '{"envs": [{"value": "canary"}',
        ENVELOPE + '\nrequest body:\n{"jobs": []}',
        ENVELOPE + "\n> PUT /v2/apps/example\nAuthorization: Bearer canary",
    ],
)
def test_raw_specs_malformed_json_and_traces_withheld(value):
    safe = json.dumps(m.validation_metadata(value))
    assert "withheld" in safe
    assert '"envs"' not in safe and '"jobs"' not in safe
    assert "canary" not in safe


def test_pinned_doctl_loopback_fixture_retains_reason_and_suppresses_canary():
    output = (ROOT / "tests/fixtures/doctl-v1.160.1-update-validation.json").read_text()
    result = m.validation_metadata("", output, ["offline-private-key-canary"])
    safe = "\n".join(result["redacted_messages"])
    assert 'field "jobs.envs.5.value": invalid value' in safe
    assert "offline-private-key-canary" not in safe


def test_synthetic_image_rejection_fixture_preserves_full_unknown_meaning():
    # Representative synthetic error, not the unknown historical provider cause.
    output = (ROOT / "tests/fixtures/doctl-v1.160.1-image-update-rejection.json").read_text()
    result = m.validation_metadata("", output, ["offline-private-key-canary"])
    assert result["redacted_messages"] == [PROSE + ' credential="[REDACTED]"']


def test_secret_collector_leaves_public_config_words_readable():
    spec = {
        "envs": [
            {"key": "PUBLIC_WORD", "value": "image"},
            {"key": "ACCOUNT", "type": "SECRET", "value": "account-canary"},
        ],
        "jobs": [{"envs": [{"key": "SPACES_ACCESS_KEY_ID", "value": "key-canary"}]}],
    }
    with patch.dict(m.os.environ, {"DIGITALOCEAN_ACCESS_TOKEN": "token-canary"}):
        values = m.diagnostic_sensitive_values(spec)
    assert set(values) == {"account-canary", "key-canary", "token-canary"}
    assert m.validation_metadata(ENVELOPE + PROSE, sensitive_values=values)[
        "redacted_messages"
    ] == [PROSE]


def test_color_escapes_cannot_split_a_known_secret_around_redaction():
    result = m.validation_metadata(
        ENVELOPE + "invalid credential token-\x1b[31mcanary; " + PROSE,
        sensitive_values=["token-canary"],
    )
    assert "canary" not in json.dumps(result)
    assert PROSE in result["redacted_messages"][0]


def test_failed_update_still_calls_once_and_never_activates():
    rendered = {"jobs": [{"envs": [{"key": "SECRET", "type": "SECRET", "value": SECRET}]}]}
    result = SimpleNamespace(
        returncode=1,
        stderr="",
        stdout=json.dumps({"errors": [{"detail": ENVELOPE + PROSE + SECRET}]}),
    )
    with (
        patch.object(
            sys,
            "argv",
            [
                "deploy",
                "--phase",
                "preflight",
                "--image-digest",
                "sha256:" + "a" * 64,
                "--credential-placement-approved",
            ],
        ),
        patch.object(m, "get", return_value={"spec": rendered}) as get,
        patch.object(m, "render", return_value=rendered),
        patch.object(m.subprocess, "run", return_value=result) as run,
        pytest.raises(RuntimeError) as exc,
    ):
        m.main()
    get.assert_called_once()
    run.assert_called_once()
    assert "sensitive-canary" not in str(exc.value)
    assert PROSE in str(exc.value)
