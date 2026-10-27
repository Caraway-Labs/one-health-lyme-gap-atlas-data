"""Offline error-preservation and unchanged deployment-boundary checks."""

import base64
import binascii
import importlib.util
import json
import os
import shutil
import subprocess
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


def _synthetic_invalid_jwt():
    """Pattern fixture only: no key material and an undecodable signature segment."""
    segments = [
        base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        for payload in ({"alg": "HS256"}, {"sub": "synthetic-canary"})
    ]
    return ".".join([*segments, "x" * 17])


def test_runtime_jwt_fixture_cannot_be_a_valid_hs256_signature():
    signature = _synthetic_invalid_jwt().split(".")[2]
    assert len(signature) % 4 == 1
    with pytest.raises((ValueError, binascii.Error)):
        base64.b64decode(signature + "=" * ((-len(signature)) % 4), altchars=b"-_", validate=True)


def test_only_exact_approved_historical_fingerprint_is_ignored():
    assert (ROOT / ".gitleaksignore").read_text().splitlines() == [
        "2f9258d511c6ed70b5fe37ab3561de988e7d66b1:"
        "tests/test_intelligence_daily_validation_diagnostics.py:jwt:82"
    ]


@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") != "true",
    reason="Pinned Docker verification executes on hosted CI, not the local missing Docker engine.",
)
def test_pinned_scanner_still_rejects_a_separate_synthetic_history_finding(tmp_path):
    image = (
        "ghcr.io/gitleaks/gitleaks@sha256:"
        "c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"
    )
    workflow = (ROOT / ".github/workflows/quality.yml").read_text()
    assert image in workflow
    assert "git /repo --config /repo/.gitleaks.toml --redact --no-banner" in workflow
    docker = shutil.which("docker")
    assert docker is not None
    fixture = tmp_path / "separate-scanner-proof"
    fixture.mkdir()
    (fixture / "canary.txt").write_text(_synthetic_invalid_jwt() + "\n")
    for filename in (".gitleaksignore", ".gitleaks.toml"):
        shutil.copyfile(ROOT / filename, fixture / filename)
    for args in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Synthetic scanner proof",
            "-c",
            "user.email=scanner@example.invalid",
            "commit",
            "-qm",
            "Synthetic local-only scanner verification",
        ],
    ):
        subprocess.run(["git", *args], cwd=fixture, capture_output=True, check=True, timeout=30)
    result = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "-v",
            f"{fixture}:/repo",
            image,
            "git",
            "/repo",
            "--config",
            "/repo/.gitleaks.toml",
            "--redact",
            "--no-banner",
            "--report-format",
            "json",
            "--report-path",
            "/repo/proof.json",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 1:
        raise AssertionError("Pinned scanner failed to reject separate synthetic fixture")
    findings = json.loads((fixture / "proof.json").read_text())
    jwt = [row for row in findings if row.get("RuleID") == "jwt"]
    if len(jwt) != 1 or jwt[0].get("File") != "canary.txt":
        raise AssertionError("Expected exactly one separate synthetic JWT finding")
    approved = (ROOT / ".gitleaksignore").read_text().strip()
    assert jwt[0]["Fingerprint"] != approved


@pytest.mark.parametrize(
    "value",
    [
        "dop_v1_" + "a" * 64,
        "ghp_" + "b" * 36,
        "github_pat_" + "c" * 50,
        "AKIA" + "D" * 16,
        "EV[opaque-provider-reference]",
        pytest.param(_synthetic_invalid_jwt(), id="synthetic-invalid-jwt"),
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
            {"key": "TOPX_ENV", "value": "prod"},
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


def test_failed_update_still_calls_once_and_never_activates(monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "test@example.invalid")
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
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
    assert "--update-sources" in run.call_args.args[0]
    assert "sensitive-canary" not in str(exc.value)
    assert PROSE in str(exc.value)


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
@pytest.mark.parametrize(
    "payload",
    [
        '{"jobs":[{"envs":[{"key":"PUBLIC_CONFIG","value":"private-config-canary"}]}]}',
        '{"jobs":[{"envs":[{"key":"PUBLIC_CONFIG","value":"private-config-canary"}',
        '[{"envs":[{"key":"PUBLIC_CONFIG","value":"private-config-canary"}]}]',
        r"{\"jobs\":[{\"envs\":[{\"value\":\"private-config-canary\"}]}]}",
        "%7b%22jobs%22%3a%22private-config-canary%22%7d",
        "%257B%2522envs%2522%253A%2522private-config-canary%2522%257D",
        r'\u007b"jobs":"private-config-canary"}',
        "jobs:\n - envs:\n   - value: private-config-canary",
    ],
)
def test_inline_specs_anywhere_after_envelope_are_withheld(channel, payload):
    detail = ENVELOPE + "invalid spec: " + payload
    stderr = detail if channel == "stderr" else ""
    stdout = json.dumps({"errors": [{"detail": detail}]}) if channel == "stdout" else ""
    message = m.update_failure(stderr, stdout)
    assert "private-config-canary" not in message
    assert "PUBLIC_CONFIG" not in message
    assert '"jobs"' not in message
    assert "invalid spec:" in message
    assert "withheld" in message


@pytest.mark.parametrize(
    "key",
    [
        "API_KEY",
        "api-key",
        "apiKey",
        "PASSWD",
        "DB_PASSWD",
        "PASSWORD",
        "AUTHORIZATION",
        "arbitrary_name",
    ],
)
@pytest.mark.parametrize("declared_type", [None, "GENERAL", "SECRET"])
@pytest.mark.parametrize("location", ["app", "jobs", "services"])
def test_all_unrecognized_env_keys_are_private_regardless_type(key, declared_type, location):
    entry = {"key": key, "value": "apikey-canary"}
    if declared_type:
        entry["type"] = declared_type
    app = {"envs": [entry]} if location == "app" else {location: [{"envs": [entry]}]}
    values = m.diagnostic_sensitive_values(app)
    assert "apikey-canary" in values
    output = json.dumps({"errors": [{"detail": ENVELOPE + "invalid value apikey-canary"}]})
    assert "apikey-canary" not in m.update_failure("", output, values)


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
@pytest.mark.parametrize(
    ("secret", "encoded"),
    [
        ("p/ss:word", "p%2Fss%3aword"),
        ("Ω/secret", "%CE%a9%2Fsecret"),
        ("p/ss:word", "p%252Fss%253aword"),
        ("Ω/secret", "%25CE%25a9%252Fsecret"),
        ("p/ss:word", "p%25252fss%25253Aword"),
    ],
)
def test_mixed_percent_hex_casing_at_each_encoding_depth(channel, secret, encoded):
    values = m.diagnostic_sensitive_values({"envs": [{"key": "API_KEY", "value": secret}]})
    detail = ENVELOPE + 'invalid value "' + encoded + '"; ' + PROSE
    stderr = detail if channel == "stderr" else ""
    stdout = json.dumps({"errors": [{"detail": detail}]}) if channel == "stdout" else ""
    message = m.update_failure(stderr, stdout, values)
    assert encoded not in message
    assert PROSE in message


def test_percent_hex_matching_does_not_casefold_literal_secret_bytes():
    result = m.validation_metadata(
        ENVELOPE + "invalid value s%2FWord; actual S%2fWord",
        sensitive_values=["S/Word"],
    )
    prose = result["redacted_messages"][0]
    assert "s%2FWord" in prose
    assert "S%2fWord" not in prose


def test_mixed_percent_encoding_redacted_before_truncation():
    detail = ENVELOPE + "x" * (m.MAX_ERROR_MESSAGE - 4) + "p%2Fss%3aword"
    result = m.validation_metadata(detail, sensitive_values=["p/ss:word"])
    assert result["truncated"]
    assert "p%2F" not in json.dumps(result)


def test_secret_type_overrides_documented_public_key():
    values = m.diagnostic_sensitive_values(
        {
            "envs": [{"key": "TOPX_ENV", "type": "secret", "value": "secret-prod-canary"}],
        }
    )
    assert "secret-prod-canary" in values
    assert "secret-prod-canary" not in m.update_failure(
        ENVELOPE + "invalid value secret-prod-canary",
        sensitive_values=values,
    )


def test_payload_opening_inside_known_secret_cannot_leak_a_cut_prefix():
    secret = "secret-prefix-canary{credential-data}"
    message = m.update_failure(ENVELOPE + "invalid value " + secret, sensitive_values=[secret])
    assert "secret-prefix-canary" not in message
