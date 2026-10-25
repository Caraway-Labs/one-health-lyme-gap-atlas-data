"""Build one temporary PROD intelligence-daily job and report its outcome.

The build mode writes the one-shot spec. The other modes read deployment
output, job logs, or spec files and print only allowlisted outcome fields.
They never echo environment values, spec bodies, or raw log lines.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import deploy_intelligence_daily as daily

EXPECTED_JOBS = daily.BASE | {daily.NAME}
MANUAL_JOB = "intelligence-daily-manual-once"
COMMAND = daily.COMMAND
RECOVER_PREFIX = (
    "/app/.venv/bin/atlas-data pipeline recover-intelligence-daily-stuck-run --ingestion-run-id "
)
# Keep aligned with intelligence_runtime.DAILY_OPERATOR_STAGES.
OPERATOR_STAGES = frozenset(
    {"CLAIM", "FETCH", "PARSE", "NORMALIZE", "WRITE", "RETENTION", "PUBLISH"}
)
OUTCOME_LOG_PREFIX = "ATLAS_INTEL_DAILY_OUTCOME "
OUTCOME_LOG_UNAVAILABLE = "OUTCOME_LOG_UNAVAILABLE"
TOPOLOGY_RESTORE_MISMATCH = "INTELLIGENCE_DAILY_TOPOLOGY_RESTORE_MISMATCH"
REASON_REQUIRED = "INTELLIGENCE_DAILY_REASON_REQUIRED"
REASON_MAX_CHARS = 200
MAX_SPEC_BYTES = 5_000_000
MAX_UPDATE_OUTPUT_BYTES = 262_144
MAX_LOG_BYTES = 2_000_000
MAX_LOG_LINES = 2_000
MAX_OUTCOME_JSON_CHARS = 8_192
_LOG_STATUSES = frozenset(
    {"COMPLETED", "FAILED", "ALREADY_CLAIMED", "SCHEDULE_SUPPRESSED", "READY"}
)
_STATUS_FOR_OUTCOME = {
    "SUCCEEDED": "COMPLETED",
    "FAILED": "FAILED",
    "ALREADY_CLAIMED": "ALREADY_CLAIMED",
    "SCHEDULE_SUPPRESSED": "SCHEDULE_SUPPRESSED",
    "READY": "READY",
    "PREFLIGHT_OR_RUNTIME_FAILED": "FAILED",
}
_ALLOWLISTED_ERROR_CODE = re.compile(
    r"^(?:INTELLIGENCE_[A-Z0-9_]{3,80}|FEED_[A-Z0-9_]{1,80}|MALFORMED_FEED|"
    r"UNSUPPORTED_FEED_ENVELOPE|AMBIGUOUS_FEED_FIELD|XML_[A-Z0-9_]{3,80})$"
)
_EXCEPTION_CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,80}$")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_LABELED_DEPLOYMENT_ID = re.compile(
    r"deployment ID: (" + _UUID.pattern + r")",
    re.IGNORECASE,
)
_DECODER = json.JSONDecoder()


def build_operation_spec(
    baseline: dict[str, Any],
    *,
    preflight_only: bool,
    recover_ingestion_run_id: str = "",
    reopen_attempt: int = 1,
) -> dict[str, Any]:
    jobs = baseline.get("jobs", [])
    job_names = {job.get("name") for job in jobs if isinstance(job, dict)}
    if not isinstance(jobs, list) or job_names != EXPECTED_JOBS:
        raise PermissionError("INTELLIGENCE_DAILY_BASELINE_TOPOLOGY_REQUIRED")
    if any(job.get("kind") == "PRE_DEPLOY" for job in jobs if isinstance(job, dict)):
        raise PermissionError("INTELLIGENCE_DAILY_COMPETING_PREDEPLOY")
    template = next(job for job in jobs if job.get("name") == daily.NAME)
    digest = template.get("image", {}).get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PermissionError("INTELLIGENCE_DAILY_IMAGE_REQUIRED")
    if template.get("run_command") != COMMAND:
        raise PermissionError("INTELLIGENCE_DAILY_COMMAND_REQUIRED")
    if recover_ingestion_run_id and preflight_only:
        raise PermissionError("INTELLIGENCE_DAILY_RECOVERY_MODE_EXCLUSIVE")
    if not 1 <= reopen_attempt <= 31:
        raise PermissionError("INTELLIGENCE_DAILY_REOPEN_ATTEMPT_INVALID")
    if recover_ingestion_run_id and reopen_attempt >= 2:
        raise PermissionError("INTELLIGENCE_DAILY_RECOVERY_MODE_EXCLUSIVE")
    if reopen_attempt >= 2 and preflight_only:
        raise PermissionError("INTELLIGENCE_DAILY_REOPEN_MODE_EXCLUSIVE")
    if recover_ingestion_run_id:
        if not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            recover_ingestion_run_id,
        ):
            raise PermissionError("INTELLIGENCE_DAILY_RECOVERY_RUN_ID_REQUIRED")
        run_command = RECOVER_PREFIX + recover_ingestion_run_id
    else:
        run_command = COMMAND + (" --preflight-only" if preflight_only else "")
        if reopen_attempt >= 2:
            run_command = f"{COMMAND} --reopen-attempt {reopen_attempt}"
    manual = copy.deepcopy(template)
    manual.update(
        name=MANUAL_JOB,
        kind="PRE_DEPLOY",
        run_command=run_command,
        instance_count=1,
    )
    if reopen_attempt >= 2:
        envs = list(manual.get("envs", []))
        if not any(entry.get("key") == "INTELLIGENCE_DAILY_REOPEN" for entry in envs):
            envs.append(
                {
                    "key": "INTELLIGENCE_DAILY_REOPEN",
                    "scope": "RUN_TIME",
                    "type": "GENERAL",
                    "value": "true",
                }
            )
        manual["envs"] = envs
    manual.pop("schedule", None)
    result = copy.deepcopy(baseline)
    result["jobs"] = [job for job in jobs if job.get("name") != MANUAL_JOB] + [manual]
    return result


def published_outcome_code(code: object) -> str | None:
    """Keep a code that is allowlisted or an UNCLASSIFIED class token."""
    if not isinstance(code, str):
        return None
    if _ALLOWLISTED_ERROR_CODE.fullmatch(code):
        return code
    prefix = "UNCLASSIFIED_"
    class_name = code.removeprefix(prefix)
    if code.startswith(prefix) and _EXCEPTION_CLASS_NAME.fullmatch(class_name):
        return code
    return None


def normalize_reason(reason: str) -> str:
    """Return a one-line dispatch reason, or raise if it is empty or too long."""
    if not isinstance(reason, str) or not 1 <= len(reason) <= REASON_MAX_CHARS:
        raise ValueError(REASON_REQUIRED)
    cleaned = "".join(" " if char in "\r\n" else char for char in reason).strip()
    if not cleaned or any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise ValueError(REASON_REQUIRED)
    return cleaned.replace("::", ": :")


def _safe_source(value: object) -> str | None:
    if (
        isinstance(value, str)
        and value.isascii()
        and 1 <= len(value) <= 80
        and all(char.isalnum() or char in "-_" for char in value)
    ):
        return value
    return None


def _safe_status(payload: dict[str, Any]) -> str | None:
    status = payload.get("status")
    if isinstance(status, str) and status in _LOG_STATUSES:
        return status
    outcome = payload.get("outcome")
    if isinstance(outcome, str):
        mapped = _STATUS_FOR_OUTCOME.get(outcome)
        if mapped in _LOG_STATUSES:
            return mapped
    return None


def _outcome_seconds(timings: object) -> int:
    if not isinstance(timings, dict):
        return 0
    total = 0
    for key, value in timings.items():
        if key not in OPERATOR_STAGES:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value < 0 or value > 10**12:
            continue
        total += value
    if total > 10**12:
        total = 10**12
    return (total + 500) // 1000


def _row_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    source = _safe_source(payload.get("source_id"))
    if source is None:
        source = _safe_source(payload.get("source"))
    status = _safe_status(payload)
    if source is None or status is None:
        return None
    stage = payload.get("failed_stage")
    failed_stage = stage if isinstance(stage, str) and stage in OPERATOR_STAGES else None
    error_code = published_outcome_code(payload.get("error_code"))
    if status == "FAILED" and error_code is None:
        error_code = "UNCLASSIFIED_EXCEPTION"
    timings = payload.get("stage_timings_ms")
    seconds = payload.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        seconds = _outcome_seconds(timings)
    elif seconds < 0 or seconds > 10**9:
        seconds = 0
    return {
        "source": source,
        "status": status,
        "error_code": error_code,
        "failed_stage": failed_stage,
        "seconds": seconds,
    }


def parse_daily_outcomes(text: str) -> list[dict[str, Any]]:
    """Return the last allowlisted outcome for each source, in first-seen order."""
    rows: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(text.splitlines()):
        if index >= MAX_LOG_LINES:
            break
        marker = line.find(OUTCOME_LOG_PREFIX)
        if marker < 0:
            continue
        blob = line[marker + len(OUTCOME_LOG_PREFIX) :]
        if len(blob) > MAX_OUTCOME_JSON_CHARS:
            continue
        try:
            payload, _end = _DECODER.raw_decode(blob.lstrip())
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        row = _row_from_payload(payload)
        if row is not None:
            rows[str(row["source"])] = row
    return list(rows.values())


def format_outcome_table(rows: list[dict[str, Any]]) -> str:
    """Pipe table: source, status, error_code, failed_stage, seconds."""
    lines = ["source | status | error_code | failed_stage | seconds"]
    for row in rows:
        lines.append(
            " | ".join(
                (
                    str(row["source"]),
                    str(row["status"]),
                    str(row["error_code"] or "-"),
                    str(row["failed_stage"] or "-"),
                    str(row["seconds"]),
                )
            )
        )
    return "\n".join(lines)


def read_log_text(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_LOG_BYTES)
    except OSError:
        return ""
    return "\n".join(raw.decode("utf-8", errors="replace").splitlines()[:MAX_LOG_LINES])


def render_outcome_report(log_text: str, *, logs_missing: bool) -> tuple[str, list[dict[str, Any]]]:
    rows = parse_daily_outcomes(log_text)
    table = format_outcome_table(rows)
    if logs_missing:
        note = "Outcome logs: unavailable"
    elif not rows:
        note = "Outcome logs: no ATLAS_INTEL_DAILY_OUTCOME lines"
    else:
        note = ""
    report = f"{table}\n{note}" if note else table
    return report, rows


def deployment_id_from_update_output(text: str) -> str | None:
    """Prefer the labeled pending deployment id over the active-deployment column."""
    labeled = _LABELED_DEPLOYMENT_ID.search(text)
    if labeled:
        return labeled.group(1).lower()
    for line in text.splitlines():
        found = [item.lower() for item in _UUID.findall(line)]
        if len(found) >= 2:
            return found[1]
    return None


def read_update_output(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_UPDATE_OUTPUT_BYTES)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


class SpecDigestError(Exception):
    """A spec file could not be hashed. The message stays empty on purpose."""


def spec_digest(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SpecDigestError from exc
    if len(raw) > MAX_SPEC_BYTES:
        raise SpecDigestError
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SpecDigestError from exc
    if not isinstance(payload, dict):
        raise SpecDigestError
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def specs_match(baseline: Path, restored: Path) -> bool:
    try:
        return spec_digest(baseline) == spec_digest(restored)
    except SpecDigestError:
        return False


def load_outcome_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    raw_rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(raw_rows, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw_rows:
        if isinstance(item, dict):
            row = _row_from_payload(item)
            if row is not None:
                rows.append(row)
    return rows


def parse_operation_status(value: str) -> int:
    if value.isdigit():
        return int(value)
    return 1


def run_failed(operation_status: int, rows: list[dict[str, Any]]) -> bool:
    if operation_status != 0:
        return True
    return any(row["status"] == "FAILED" for row in rows)


def failure_codes(operation_status: int, rows: list[dict[str, Any]]) -> list[str]:
    codes: list[str] = []
    for row in rows:
        if row["status"] != "FAILED":
            continue
        code = row.get("error_code") or "UNCLASSIFIED_EXCEPTION"
        if isinstance(code, str) and code not in codes:
            codes.append(code)
    if codes:
        return codes
    if operation_status != 0:
        return [OUTCOME_LOG_UNAVAILABLE]
    return []


def daily_operation_message(*, failed: bool, codes: list[str], restored: bool) -> str:
    restored_word = "yes" if restored else "no"
    verdict = f"Baseline topology restored: {restored_word} (verified by spec digest compare)."
    if not failed:
        return f"Daily operation completed. {verdict}"
    rendered = ", ".join(codes) if codes else OUTCOME_LOG_UNAVAILABLE
    return f"Daily operation FAILED: {rendered}. {verdict}"


def topology_restore_mismatch_line() -> str:
    return f"{TOPOLOGY_RESTORE_MISMATCH}: topology restoration failed"


def result_lines(*, operation_status: int, rows: list[dict[str, Any]], restored: bool) -> list[str]:
    failed = run_failed(operation_status, rows)
    lines = [
        daily_operation_message(
            failed=failed,
            codes=failure_codes(operation_status, rows) if failed else [],
            restored=restored,
        )
    ]
    if not restored:
        lines.append(topology_restore_mismatch_line())
    return lines


def result_exit_code(*, operation_status: int, rows: list[dict[str, Any]], restored: bool) -> int:
    if restored and not run_failed(operation_status, rows):
        return 0
    return 1


def append_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def _write_rows(path: Path, rows: list[dict[str, Any]], *, logs_missing: bool) -> None:
    path.write_text(
        json.dumps({"logs_missing": logs_missing, "rows": rows}, separators=(",", ":")),
        encoding="utf-8",
    )


def _build(args: argparse.Namespace) -> int:
    if args.baseline is None or args.output is None:
        print("build requires --baseline and --output", file=sys.stderr)
        return 2
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    args.output.write_text(
        json.dumps(
            build_operation_spec(
                baseline,
                preflight_only=args.preflight_only,
                recover_ingestion_run_id=args.recover_ingestion_run_id,
                reopen_attempt=args.reopen_attempt,
            )
        ),
        encoding="utf-8",
    )
    return 0


def _validate_reason(reason: str) -> int:
    try:
        cleaned = normalize_reason(reason)
    except ValueError:
        length = len(reason) if isinstance(reason, str) else -1
        print(f"::error::{REASON_REQUIRED} length={length}", file=sys.stderr)
        return 1
    line = f"Dispatch reason: {cleaned}"
    print(line)
    append_summary(line)
    return 0


def _deployment_id(path: Path | None) -> int:
    text = read_update_output(path) if path is not None else ""
    found = deployment_id_from_update_output(text)
    if found is None:
        print("deployment id unavailable", file=sys.stderr)
        return 1
    print(found)
    return 0


def _render_outcomes(args: argparse.Namespace) -> int:
    if args.logs is None or args.rows is None:
        print("render-outcomes requires --logs and --rows", file=sys.stderr)
        return 2
    log_text = "" if args.logs_missing else read_log_text(args.logs)
    report, rows = render_outcome_report(log_text, logs_missing=args.logs_missing)
    print(report)
    append_summary(report)
    _write_rows(args.rows, rows, logs_missing=args.logs_missing)
    return 0


def _compare_specs(args: argparse.Namespace) -> int:
    if args.baseline is None or args.restored is None:
        print("compare-specs requires --baseline and --restored", file=sys.stderr)
        return 2
    return 0 if specs_match(args.baseline, args.restored) else 1


def _render_result(args: argparse.Namespace) -> int:
    if args.restored_flag not in {"yes", "no"}:
        print("render-result requires --restored-flag yes or no", file=sys.stderr)
        return 2
    rows = load_outcome_rows(args.rows)
    restored = args.restored_flag == "yes"
    status = parse_operation_status(args.operation_status)
    plain = result_lines(operation_status=status, rows=rows, restored=restored)
    for line in plain:
        if line.startswith("Daily operation FAILED:") or line.startswith(TOPOLOGY_RESTORE_MISMATCH):
            print(f"::error::{line}")
        else:
            print(line)
    append_summary("\n".join(plain))
    return result_exit_code(operation_status=status, rows=rows, restored=restored)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=(
            "build",
            "validate-reason",
            "deployment-id",
            "render-outcomes",
            "compare-specs",
            "render-result",
        ),
        default="build",
    )
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--restored", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--recover-ingestion-run-id", default="")
    parser.add_argument("--reopen-attempt", type=int, default=1)
    parser.add_argument("--reason", default="")
    parser.add_argument("--deployment-output", type=Path)
    parser.add_argument("--logs", type=Path)
    parser.add_argument("--rows", type=Path)
    parser.add_argument("--operation-status", default="0")
    parser.add_argument("--restored-flag", choices=("yes", "no"))
    parser.add_argument("--logs-missing", action="store_true")
    args = parser.parse_args(argv)
    handlers = {
        "build": lambda: _build(args),
        "validate-reason": lambda: _validate_reason(args.reason),
        "deployment-id": lambda: _deployment_id(args.deployment_output),
        "render-outcomes": lambda: _render_outcomes(args),
        "compare-specs": lambda: _compare_specs(args),
        "render-result": lambda: _render_result(args),
    }
    raise SystemExit(handlers[args.mode]())


if __name__ == "__main__":
    main()
