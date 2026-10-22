import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "daily_diagnostics", Path(__file__).parents[1] / "scripts/deploy_intelligence_daily.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
safe_failure = module.validation_metadata

RID = "39bd6bbe-face-4553-b470-c07f0e502d15"
PREFIX = f'PUT https://api.digitalocean.com/v2/apps/example: 400 (request "{RID}") '


class DiagnosticsTests(unittest.TestCase):
    def test_recorded_pinned_cli_loopback_json_fixture(self):
        # Synthetic local PUT rejection, actual doctl 1.160.1 JSON stdout shape.
        output = (
            Path(__file__).parent / "fixtures/doctl-v1.160.1-update-validation.json"
        ).read_text()
        result = safe_failure("", output, ["offline-private-key-canary"])
        self.assertEqual(result["request_id"], "c3041e18-5aa5-4b2c-bbc5-9ef53bc828d0")
        self.assertEqual(result["validation_fields"], ["jobs.envs.[].value"])
        self.assertNotIn("offline-private-key-canary", json.dumps(result))

    def test_failed_update_redacts_spec_values_and_never_continues_or_retries(self):
        secret = "invalid encrypted secret"
        rendered = {
            "envs": [{"value": "app-env-canary"}],
            "jobs": [{"envs": [{"value": secret}]}],
        }
        result = SimpleNamespace(
            returncode=1,
            stderr="",
            stdout=json.dumps({"errors": [{"detail": PREFIX + secret + " token-canary"}]}),
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
            patch.object(module, "get", return_value={"spec": rendered}) as get,
            patch.object(module, "render", return_value=rendered),
            patch.object(module.subprocess, "run", return_value=result) as run,
            patch.dict(module.os.environ, {"DIGITALOCEAN_ACCESS_TOKEN": "token-canary"}),
            self.assertRaises(RuntimeError) as raised,
        ):
            module.main()
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("token-canary", str(raised.exception))
        run.assert_called_once()
        get.assert_called_once()  # No activation/readback follows a rejected update.
        self.assertEqual(run.call_args.args[0][1:3], ["apps", "update"])

    def test_collector_covers_app_and_all_component_values(self):
        spec = {
            "envs": [{"value": "app"}],
            "services": [{"envs": [{"value": "service"}]}],
            "jobs": [{"envs": [{"value": "job"}]}],
        }
        with patch.dict(module.os.environ, {"DIGITALOCEAN_ACCESS_TOKEN": "token"}):
            self.assertEqual(
                set(module.diagnostic_sensitive_values(spec)), {"app", "service", "job", "token"}
            )

    def test_pinned_doctl_json_stdout_shape(self):
        detail = (
            PREFIX + 'errors validating app spec; first error in field "jobs.envs.5.value": '
            "value is invalid"
        )
        out = safe_failure("", json.dumps({"errors": [{"detail": detail}]}))
        self.assertEqual(out["status"], "400")
        self.assertEqual(out["request_id"], RID)
        self.assertEqual(out["validation_fields"], ["jobs.envs.[].value"])
        self.assertIn("invalid", out["reason_tokens"])

    def test_stderr_channel_and_previously_unclassified_reason(self):
        out = safe_failure(PREFIX + 'field "jobs.image.registry": image registry does not exist')
        self.assertEqual(out["validation_fields"], ["jobs.image.registry"])
        self.assertIn("exist", out["reason_tokens"])
        self.assertFalse(out["root_cause_established"])

    def test_secret_values_in_field_and_reason_are_removed(self):
        secret = "invalid encrypted secret"
        output = safe_failure(
            PREFIX
            + f'field "jobs.{secret}.value": {secret} private-key-canary EV[ciphertext-canary]',
            sensitive_values=[secret],
        )
        encoded = json.dumps(output)
        for canary in (secret, "private-key-canary", "ciphertext-canary"):
            self.assertNotIn(canary, encoded)
        self.assertEqual(output["validation_fields"], [])
        self.assertNotIn("encrypted", output["reason_tokens"])

    def test_untrusted_fields_and_html_do_not_escape(self):
        out = safe_failure(
            PREFIX + 'field "jobs.secret_canary.value": <script>private_key_canary</script>'
        )
        self.assertEqual(out["validation_fields"], [])
        self.assertNotIn("canary", json.dumps(out))

    def test_malformed_empty_and_wrong_json_types(self):
        for value in ("{", "[]", '{"errors":[null,{}, {"detail":123}]}', ""):
            with self.subTest(value=value):
                out = safe_failure("", value)
                self.assertEqual(out["status"], "UNKNOWN")
                self.assertEqual(out["validation_fields"], [])

    def test_multiple_errors_and_output_bounds(self):
        errors = [
            {"detail": PREFIX + f'field "jobs.{i}.name": duplicate name ' + "private_canary " * 200}
            for i in range(40)
        ]
        out = safe_failure("", json.dumps({"errors": errors}))
        self.assertEqual(out["validation_fields"], ["jobs.[].name"])
        self.assertLessEqual(len(out["reason_tokens"]), 96)
        self.assertNotIn("private_canary", json.dumps(out))

    def test_valid_schema_bracket_index(self):
        out = safe_failure(PREFIX + 'field "jobs[3].schedule.cron": required')
        self.assertEqual(out["validation_fields"], ["jobs.[].schedule.cron"])


if __name__ == "__main__":
    unittest.main()
