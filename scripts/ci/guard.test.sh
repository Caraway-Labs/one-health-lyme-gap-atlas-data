#!/usr/bin/env bash
# Pass and fail cases for scripts/ci/guard.sh.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
helper="$root/scripts/ci/guard.sh"

sentinel="$(mktemp)"
printf 'sentinel\n' >"$sentinel"
export GITHUB_STEP_SUMMARY="$sentinel"

die() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

invoke() {
  local mode="$1"
  shift
  local summary_file=""
  local -a cmd
  if [[ "$mode" == "summary" ]]; then
    summary_file="$(mktemp)"
    cmd=(env "GITHUB_STEP_SUMMARY=$summary_file")
  else
    cmd=(env -u GITHUB_STEP_SUMMARY)
  fi
  set +e
  # $1 and $@ belong to the inner bash process. Single quotes keep the outer shell from expanding them.
  # shellcheck disable=SC2016
  INVOKE_OUTPUT="$("${cmd[@]}" bash -c 'source "$1"; shift; "$@"' bash "$helper" "$@" 2>&1)"
  INVOKE_STATUS=$?
  set -e
  if [[ -n "$summary_file" ]]; then
    INVOKE_SUMMARY="$(<"$summary_file")"
    rm -f "$summary_file"
  else
    INVOKE_SUMMARY=""
  fi
}

assert_status() {
  local want="$1"
  [[ "$INVOKE_STATUS" -eq "$want" ]] || die "status want=$want got=$INVOKE_STATUS output=$INVOKE_OUTPUT"
}

assert_output() {
  [[ "$INVOKE_OUTPUT" == "$1" ]] || die "output want=[$1] got=[$INVOKE_OUTPUT]"
}

assert_summary_matches_output() {
  [[ "$INVOKE_SUMMARY" == "$INVOKE_OUTPUT" ]] || die "summary [$INVOKE_SUMMARY] != output [$INVOKE_OUTPUT]"
}

set +e
exec_output="$(bash "$helper" 2>&1)"
exec_status=$?
set -e
[[ "$exec_status" -eq 1 ]] || die "direct execution status=$exec_status"
[[ "$exec_output" == *"source scripts/ci/guard.sh"* ]] || die "direct execution output=$exec_output"

invoke none guard_eq digest_match sha256:abc sha256:abc "Re-run with the reviewed digest."
assert_status 0
assert_output "ok digest_match"
[[ -z "$INVOKE_SUMMARY" ]] || die "success wrote a summary"

invoke summary guard_eq digest_match sha256:abc sha256:def "The DEV image digest does not match IMAGE_DIGEST. Re-run with the digest from the latest successful deploy-dev run."
assert_status 1
assert_output "::error title=digest_match::expected=sha256:abc received=sha256:def remediation=The DEV image digest does not match IMAGE_DIGEST. Re-run with the digest from the latest successful deploy-dev run."
assert_summary_matches_output
[[ "$INVOKE_OUTPUT" != *"ok "* ]] || die "failure printed ok"

invoke none guard_eq empty_match "" "" "keep going"
assert_status 0
assert_output "ok empty_match"

invoke summary guard_ne flag_absent true false "Redispatch with the flag false."
assert_status 0
assert_output "ok flag_absent"

invoke summary guard_ne flag_absent true true "Redispatch with the flag false."
assert_status 1
assert_output "::error title=flag_absent::expected=!= true received=true remediation=Redispatch with the flag false."
assert_summary_matches_output

invoke none guard_gt quality_checks 0 1 "No successful Quality run was found for this commit. Wait for Quality to pass on main before dispatching."
assert_status 0
assert_output "ok quality_checks"

invoke summary guard_gt quality_checks 0 0 "No successful Quality run was found for this commit. Wait for Quality to pass on main before dispatching."
assert_status 1
assert_output "::error title=quality_checks::expected=> 0 received=0 remediation=No successful Quality run was found for this commit. Wait for Quality to pass on main before dispatching."
assert_summary_matches_output

invoke summary guard_gt quality_checks 0 abc "No successful Quality run was found for this commit. Wait for Quality to pass on main before dispatching."
assert_status 1
[[ "$INVOKE_OUTPUT" == *"received=abc"* ]] || die "non-integer received missing: $INVOKE_OUTPUT"

invoke none guard_true accounting_confirmed true "Redispatch with accounting_confirmed=true."
assert_status 0
assert_output "ok accounting_confirmed"

invoke summary guard_true accounting_confirmed false "Redispatch with accounting_confirmed=true."
assert_status 1
assert_output "::error title=accounting_confirmed::expected=true received=false remediation=Redispatch with accounting_confirmed=true."
assert_summary_matches_output

invoke none guard_nonempty image_digest sha256:abc "IMAGE_DIGEST is empty."
assert_status 0
assert_output "ok image_digest"

invoke summary guard_nonempty image_digest "" "IMAGE_DIGEST is empty."
assert_status 1
assert_output "::error title=image_digest::expected=non-empty received= remediation=IMAGE_DIGEST is empty."
assert_summary_matches_output

invoke none guard_one_of expected_pending_json '[{"version":"V162"}]' "Redispatch with one exact allowed pending set." '[{"version":"V150"}]' '[{"version":"V162"}]'
assert_status 0
assert_output "ok expected_pending_json"
[[ "$INVOKE_OUTPUT" != *'V162'* || "$INVOKE_OUTPUT" == "ok expected_pending_json" ]] || die "success echoed JSON"

invoke summary guard_one_of expected_pending_json '[{"version":"nope"}]' "Redispatch with one exact allowed pending set." '[{"version":"V150"}]' '[{"version":"V162"}]'
assert_status 1
[[ "$INVOKE_OUTPUT" == *"received="*'[{"version":"nope"}]'* ]] || die "received JSON missing: $INVOKE_OUTPUT"
[[ "$INVOKE_OUTPUT" == *'[{"version":"V150"}] | [{"version":"V162"}]'* ]] || die "allowed list missing: $INVOKE_OUTPUT"
[[ "$INVOKE_OUTPUT" == *"remediation=Redispatch with one exact allowed pending set."* ]] || die "remediation missing"
assert_summary_matches_output

invoke summary guard_eq percent_guard '100%' '50%' "use the reviewed value"
assert_status 1
[[ "$INVOKE_OUTPUT" == *"expected=100%25 received=50%25"* ]] || die "percent encoding missing: $INVOKE_OUTPUT"
[[ "$INVOKE_OUTPUT" != *$'\n'* ]] || die "annotation split across lines"

invoke summary guard_eq newline_guard $'line1\nline2' $'got\nvalue' "keep the annotation on one line"
assert_status 1
[[ "$INVOKE_OUTPUT" == *"expected=line1%0Aline2 received=got%0Avalue"* ]] || die "newline encoding missing: $INVOKE_OUTPUT"
[[ "$INVOKE_OUTPUT" != *$'\n'* ]] || die "newline annotation split"

# Same values allowed and blocked as the shell test builtin.
compare_eq() {
  local expected="$1"
  local actual="$2"
  local test_status
  if test "$actual" = "$expected"; then
    test_status=0
  else
    test_status=1
  fi
  invoke none guard_eq cmp "$expected" "$actual" "remediate"
  if [[ "$test_status" -eq 0 ]]; then
    assert_status 0
  else
    assert_status 1
  fi
}

compare_eq "refs/heads/main" "refs/heads/main"
compare_eq "refs/heads/main" "refs/heads/feature"
compare_eq "[]" "[]"
compare_eq "[]" "[ ]"
compare_eq "" "false"
compare_eq "true" "true"
compare_eq "false:false:false" "false:false:false"
compare_eq "false:false:false" "true:false:false"

compare_ne() {
  local unexpected="$1"
  local actual="$2"
  local test_status
  if test "$actual" != "$unexpected"; then
    test_status=0
  else
    test_status=1
  fi
  invoke none guard_ne cmp "$unexpected" "$actual" "remediate"
  if [[ "$test_status" -eq 0 ]]; then
    assert_status 0
  else
    assert_status 1
  fi
}

compare_ne "true" "false"
compare_ne "true" "true"
compare_ne "true:true" "false:true"
compare_ne "true:true" "true:true"

compare_nonempty() {
  local actual="$1"
  local test_status
  if test -n "$actual"; then
    test_status=0
  else
    test_status=1
  fi
  invoke none guard_nonempty cmp "$actual" "remediate"
  if [[ "$test_status" -eq 0 ]]; then
    assert_status 0
  else
    assert_status 1
  fi
}

compare_nonempty "sha256:abc"
compare_nonempty ""

compare_gt() {
  local threshold="$1"
  local actual="$2"
  local test_status
  if test "$actual" -gt "$threshold" 2>/dev/null; then
    test_status=0
  else
    test_status=1
  fi
  invoke none guard_gt cmp "$threshold" "$actual" "remediate"
  if [[ "$test_status" -eq 0 ]]; then
    assert_status 0
  else
    assert_status 1
  fi
}

compare_gt 0 1
compare_gt 0 0
compare_gt 0 2
compare_gt 0 ""
compare_gt 0 abc
compare_gt 0 -1

[[ "$(cat "$sentinel")" == "sentinel" ]] || die "guard wrote the parent step summary: [$(cat "$sentinel")]"

printf '%s\n' "guard.sh tests passed"
