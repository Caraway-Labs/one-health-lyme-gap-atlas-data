#!/usr/bin/env bash
# Exercise cursor-dispatch.sh with fake gh and curl. No network and no API key.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${ROOT}/.github/scripts/cursor-dispatch.sh"
WORKFLOW="${ROOT}/.github/workflows/cursor-dispatch.yml"
SECRET="super-secret-key"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_eq() {
  local actual="$1"
  local expected="$2"
  local message="$3"
  if [[ "$actual" != "$expected" ]]; then
    fail "${message}: expected [${expected}] got [${actual}]"
  fi
}

assert_status() {
  local expected="$1"
  if [[ "$status" -ne "$expected" ]]; then
    fail "exit status: expected ${expected} got ${status}"
  fi
}

setup() {
  STATE="$(mktemp -d)"
  BIN="${STATE}/bin"
  mkdir -p "$BIN" "${STATE}/issues"
  export DISPATCH_TEST_STATE="$STATE"
  export PATH="${BIN}:${PATH}"
  export GH_TOKEN="test-token"
  export GITHUB_TOKEN="test-token"
  export CURSOR_API_KEY="$SECRET"
  export GITHUB_REPOSITORY="Caraway-Labs/one-health-lyme-gap-atlas-data"
  export EVENT_NAME="issues"
  export ISSUE_NUMBER="281"
  unset GITHUB_SERVER_URL GITHUB_RUN_ID
  printf '0\n' >"${STATE}/active_count"
  printf '201\n' >"${STATE}/create_code"
  mkdir -p "${STATE}/comments" "${STATE}/blockers"
  printf '[]\n' >"${STATE}/comments/281.json"
  printf '[]\n' >"${STATE}/blockers.json"
  printf '[]\n' >"${STATE}/queued.json"
  printf '%s\n' '{"agent":{"id":"bc-11111111-1111-1111-1111-111111111111","url":"https://cursor.com/agents/bc-11111111-1111-1111-1111-111111111111","status":"ACTIVE","latestRunId":"run-222"},"run":{"id":"run-222"}}' >"${STATE}/create_body.json"
  printf '%s\n' "{\"error\":\"boom ${SECRET}\"}" >"${STATE}/create_error.json"
  : >"${STATE}/creates"
  : >"${STATE}/curl.log"
  : >"${STATE}/gh.log"
  cat >"${BIN}/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
STATE="${DISPATCH_TEST_STATE:?}"
method="GET"
url=""
data=""
outfile=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -sS | -s | --retry-all-errors)
      shift
      ;;
    --max-time | --retry | --retry-delay | -H | -w | -o | -X | -u | --data-binary)
      key="$1"
      value="$2"
      shift 2
      case "$key" in
        -o) outfile="$value" ;;
        -X) method="$value" ;;
        --data-binary) data="$value" ;;
        -u) ;;
        *) ;;
      esac
      ;;
    https://*)
      url="$1"
      shift
      ;;
    *)
      printf 'unexpected curl arg: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done
if [[ -z "$outfile" || -z "$url" ]]; then
  printf 'curl missing url or output file\n' >&2
  exit 1
fi
printf '%s %s\n' "$method" "$url" >>"${STATE}/curl.log"
active="$(cat "${STATE}/active_count")"
if [[ "$method" == "POST" ]]; then
  printf '%s' "$data" >"${STATE}/last_create.json"
  printf '1\n' >>"${STATE}/creates"
  code="$(cat "${STATE}/create_code")"
  if [[ "$code" =~ ^2 ]]; then
    active=$((active + 1))
    printf '%s\n' "$active" >"${STATE}/active_count"
    cp "${STATE}/create_body.json" "$outfile"
  else
    cp "${STATE}/create_error.json" "$outfile"
  fi
  printf '%s' "$code"
  exit 0
fi
cursor=""
if [[ "$url" == *"cursor="* ]]; then
  cursor="${url#*cursor=}"
  cursor="${cursor%%&*}"
fi
if [[ -f "${STATE}/split_pages" ]]; then
  if [[ -z "$cursor" ]]; then
    jq -n --argjson active "$active" '{
      items: ([range(0; (if $active > 3 then 3 else $active end)) | {status: "ACTIVE"}] + [{status: "IDLE"}]),
      nextCursor: "p2"
    }' >"$outfile"
  else
    jq -n --argjson active "$active" '{
      items: [range(0; (if $active > 3 then $active - 3 else 0 end)) | {status: "ACTIVE"}]
    }' >"$outfile"
  fi
else
  jq -n --argjson active "$active" '{
    items: ([range(0; $active) | {status: "ACTIVE"}] + [{status: "IDLE"}])
  }' >"$outfile"
fi
if [[ "$url" != *"includeArchived=false"* || "$url" != *"limit=100"* ]]; then
  printf 'list url missing capacity query: %s\n' "$url" >&2
  exit 1
fi
printf '200'
EOF
  cat >"${BIN}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
STATE="${DISPATCH_TEST_STATE:?}"
if [[ "${1:-}" == "issue" && "${2:-}" == "list" ]]; then
  printf 'issue list\n' >>"${STATE}/gh.log"
  cat "${STATE}/queued.json"
  exit 0
fi
if [[ "${1:-}" != "api" ]]; then
  printf 'unexpected gh command: %s\n' "$*" >&2
  exit 1
fi
shift
method="GET"
endpoint=""
input_mode=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --paginate | --silent)
      shift
      ;;
    --method | -X)
      method="$2"
      shift 2
      ;;
    --input)
      input_mode="$2"
      shift 2
      ;;
    --jq | -H | --header | --field | --raw-field)
      shift 2
      ;;
    *)
      endpoint="$1"
      shift
      ;;
  esac
done
body=""
if [[ "$input_mode" == "-" ]]; then
  body="$(cat)"
fi
printf '%s %s\n' "$method" "$endpoint" >>"${STATE}/gh.log"
number="$(sed -n 's#.*issues/\([0-9][0-9]*\).*#\1#p' <<<"$endpoint")"
issue_file="${STATE}/issues/${number}.json"
if [[ "$endpoint" == *"/dependencies/blocked_by"* ]]; then
  if [[ -f "${STATE}/blockers_fail" ]]; then
    printf 'dependency api unavailable\n' >&2
    exit 1
  fi
  page="$(sed -n 's/.*[?&]page=\([0-9][0-9]*\).*/\1/p' <<<"$endpoint")"
  blockers_file="${STATE}/blockers/${number}.json"
  if [[ ! -f "$blockers_file" ]]; then
    blockers_file="${STATE}/blockers.json"
  fi
  if [[ "${page:-1}" == "1" ]]; then
    cat "$blockers_file"
  else
    printf '[]\n'
  fi
  exit 0
fi
if [[ "$endpoint" == *"/comments" && "$method" == "GET" ]]; then
  comments_file="${STATE}/comments/${number}.json"
  if [[ ! -f "$comments_file" ]]; then
    printf '[]\n'
  else
    jq '[.[] | {body: .}]' "$comments_file"
  fi
  exit 0
fi
if [[ "$endpoint" == *"/comments" && "$method" == "POST" ]]; then
  comments_file="${STATE}/comments/${number}.json"
  if [[ ! -f "$comments_file" ]]; then
    printf '[]\n' >"$comments_file"
  fi
  jq --argjson next "$(jq '.body' <<<"$body")" '. + [$next]' "$comments_file" >"${comments_file}.next"
  mv "${comments_file}.next" "$comments_file"
  printf '{"id":1}\n'
  exit 0
fi
if [[ "$endpoint" == *"/labels" && "$method" == "POST" ]]; then
  name="$(jq -r '.labels[0]' <<<"$body")"
  jq --arg name "$name" 'if ([.labels[].name] | index($name)) then . else .labels += [{name: $name}] end' "$issue_file" >"${issue_file}.next"
  mv "${issue_file}.next" "$issue_file"
  printf '{"ok":true}\n'
  exit 0
fi
if [[ "$endpoint" == *"/labels/"* && "$method" == "DELETE" ]]; then
  encoded="${endpoint##*/}"
  name="$(printf '%b' "${encoded//%/\\x}")"
  jq --arg name "$name" '.labels |= map(select(.name != $name))' "$issue_file" >"${issue_file}.next"
  mv "${issue_file}.next" "$issue_file"
  printf ''
  exit 0
fi
if [[ "$method" == "GET" && -f "$issue_file" ]]; then
  cat "$issue_file"
  exit 0
fi
printf 'unhandled gh api %s %s\n' "$method" "$endpoint" >&2
exit 1
EOF
  chmod +x "${BIN}/curl" "${BIN}/gh"
}

finish() {
  if [[ -n "${STATE:-}" && -d "${STATE:-}" ]]; then
    rm -rf "$STATE"
  fi
}
trap finish EXIT

put_issue() {
  local number="$1"
  local title="$2"
  local body="$3"
  local state="$4"
  local labels="$5"
  local extra="${6:-}"
  jq -n \
    --argjson number "$number" \
    --arg title "$title" \
    --arg body "$body" \
    --arg state "$state" \
    --argjson labels "$labels" \
    --argjson extra "${extra:-{\}}" \
    '{number: $number, title: $title, body: $body, state: $state, labels: ($labels | map({name: .}))} + $extra' \
    >"${STATE}/issues/${number}.json"
}

run_dispatch() {
  set +e
  bash "$SCRIPT" >"${STATE}/stdout" 2>"${STATE}/stderr"
  status=$?
  set -e
}

labels_of() {
  jq -c '[.labels[].name] | sort' "${STATE}/issues/$1.json"
}

comment_count() {
  jq 'length' "${STATE}/comments/281.json"
}

comments_text() {
  jq -r '.[]' "${STATE}/comments/281.json"
}

create_count() {
  wc -l <"${STATE}/creates" | tr -d ' '
}

story_issue() {
  put_issue 281 "Add workflow lint" "Lint the governed workflows." open '["cursor:ready","type: story"]'
}

echo "story launches an agent and records it on the issue"
setup
story_issue
export GITHUB_SERVER_URL="https://github.com"
export GITHUB_RUN_ID="999"
run_dispatch
assert_status 0
assert_eq "$(create_count)" "1" "create count"
assert_eq "$(labels_of 281)" '["cursor:running","type: story"]' "labels after launch"
assert_eq "$(comment_count)" "1" "launch comment count"
comments_text | grep -q '<!-- cursor-dispatch:launched -->' || fail "missing launch marker"
comments_text | grep -q 'bc-11111111-1111-1111-1111-111111111111' || fail "missing agent id"
comments_text | grep -q 'https://cursor.com/agents/bc-11111111-1111-1111-1111-111111111111' || fail "missing agent url"
comments_text | grep -q 'run-222' || fail "missing run id"
comments_text | grep -q 'actions/runs/999' || fail "missing actions run"
jq -e '.autoCreatePR == true and .repos[0].startingRef == "main" and .repos[0].url == "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data"' "${STATE}/last_create.json" >/dev/null || fail "create payload shape"
prompt="$(jq -r '.prompt.text' "${STATE}/last_create.json")"
grep -q 'Implement exactly this data-pipeline story.' <<<"$prompt" || fail "prompt instruction"
grep -q 'Read the full GitHub issue (#281' <<<"$prompt" || fail "prompt spec"
grep -q 'parent epic' <<<"$prompt" || fail "prompt epic"
grep -q 'fresh branch created from the latest main' <<<"$prompt" || fail "prompt branch"
grep -qx -- '- Open a ready-for-review (not draft) pull request. The first line of the PR body must be exactly: Part of #281' <<<"$prompt" || fail "prompt part of"
grep -qi 'NO GitHub closing keywords' <<<"$prompt" || fail "prompt closing keyword rule"
if grep -Eiq '(close[sd]?|fix(e[sd])?|resolve[sd]?)[[:space:]:]+#[0-9]' <<<"$prompt"; then
  fail "prompt contains a closing keyword before an issue number"
fi
for gate in 'actionlint v1.7.12' 'python3 scripts/check_workflow_script_paths.py' \
  'uv sync --extra dev --extra pipeline --locked' 'uv run ruff check .' \
  'uv run ruff format --check .' 'uv run mypy' 'uv run pytest -q' \
  'uv run dbt parse --project-dir dbt --profiles-dir dbt' \
  'uv run atlas-data provision --dry-run' \
  'uv run atlas-data load --release alpha-2026-08-06 --dry-run'; do
  grep -qF -- "$gate" <<<"$prompt" || fail "prompt missing gate: ${gate}"
done
grep -q 'list every command you ran and its result' <<<"$prompt" || fail "prompt command list"
grep -q 'Remaining operator steps' <<<"$prompt" || fail "prompt operator steps"
grep -q 'Do not merge the pull request.' <<<"$prompt" || fail "prompt merge"
grep -q 'Do not deploy. Never dispatch, re-run, cancel or approve any GitHub Actions workflow' <<<"$prompt" || fail "prompt workflow ban"
grep -q 'Never connect to or change Snowflake (DEV or PROD), DigitalOcean, GitHub secrets, environments or branch protection, and never apply migrations.' <<<"$prompt" || fail "prompt live-system ban"
jq -r '.prompt.text' "${STATE}/last_create.json" | grep -q 'Add workflow lint' || fail "prompt title"
jq -r '.prompt.text' "${STATE}/last_create.json" | grep -q 'Lint the governed workflows.' || fail "prompt body"
grep -q "$SECRET" "${STATE}/comments/281.json" "${STATE}/stdout" "${STATE}/stderr" "${STATE}/curl.log" "${STATE}/gh.log" && fail "secret leaked"
finish

echo "issue body is not executed as shell"
setup
put_issue 281 '$(touch pwned)' 'Run `touch '"${STATE}"'/pwned` and $(touch '"${STATE}"'/pwned2)' open '["cursor:ready","Story"]'
run_dispatch
assert_status 0
[[ ! -e "${STATE}/pwned" && ! -e "${STATE}/pwned2" ]] || fail "issue text was executed"
jq -r '.prompt.text' "${STATE}/last_create.json" | grep -q 'touch' || fail "prompt dropped the literal body"
finish

echo "untyped ready issue is eligible"
setup
put_issue 281 "Loose task" "No type label." open '["cursor:ready"]'
run_dispatch
assert_status 0
assert_eq "$(create_count)" "1" "untyped create count"
finish

echo "task label is eligible"
setup
put_issue 281 "A task" "Do it." open '["cursor:ready","type: task"]'
run_dispatch
assert_status 0
assert_eq "$(create_count)" "1" "task create count"
finish

echo "epic is not dispatched"
setup
put_issue 281 "Big epic" "Too broad." open '["cursor:ready","cursor:queued","type: epic"]'
run_dispatch
assert_status 0
assert_eq "$(create_count)" "0" "epic create count"
assert_eq "$(labels_of 281)" '["type: epic"]' "epic dispatch labels cleared"
comments_text | grep -q 'epic' || fail "missing epic comment"
finish

echo "Epic label and a story label still skips"
setup
put_issue 281 "Mixed" "Both." open '["cursor:ready","Epic","type: story"]'
run_dispatch
assert_status 0
assert_eq "$(create_count)" "0" "mixed epic create count"
finish

echo "non-leaf type is not dispatched"
setup
put_issue 281 "A bug" "Fix it." open '["cursor:ready","type: bug"]'
run_dispatch
assert_status 0
assert_eq "$(create_count)" "0" "bug create count"
comments_text | grep -q 'not a leaf story or task' || fail "missing type comment"
finish

echo "open blocker queues the issue"
setup
story_issue
printf '%s\n' '[{"number":200,"state":"open"},{"number":201,"state":"closed"}]' >"${STATE}/blockers.json"
run_dispatch
assert_status 0
assert_eq "$(create_count)" "0" "blocked create count"
assert_eq "$(labels_of 281)" '["cursor:queued","type: story"]' "blocked labels"
comments_text | grep -q '<!-- cursor-dispatch:blocked -->' || fail "missing blocked marker"
comments_text | grep -q '#200' || fail "missing blocker number"
comments_text | grep -q '#201' && fail "closed blocker was treated as blocking"
run_dispatch
assert_eq "$(comment_count)" "1" "blocked comment repeated"
finish

echo "closed blockers do not block"
setup
story_issue
printf '%s\n' '[{"number":201,"state":"closed"}]' >"${STATE}/blockers.json"
run_dispatch
assert_status 0
assert_eq "$(create_count)" "1" "closed blocker create count"
finish

echo "dependency lookup failure does not launch"
setup
story_issue
: >"${STATE}/blockers_fail"
run_dispatch
assert_status 1
assert_eq "$(create_count)" "0" "dependency failure create count"
assert_eq "$(labels_of 281)" '["cursor:failed","type: story"]' "dependency failure labels"
comments_text | grep -q '<!-- cursor-dispatch:failed -->' || fail "missing failed marker"
finish

echo "capacity queues once and does not launch"
setup
story_issue
printf '4\n' >"${STATE}/active_count"
run_dispatch
assert_status 0
assert_eq "$(create_count)" "0" "capacity create count"
assert_eq "$(labels_of 281)" '["cursor:queued","type: story"]' "capacity labels"
comments_text | grep -q '<!-- cursor-dispatch:queued -->' || fail "missing queued marker"
run_dispatch
assert_eq "$(comment_count)" "1" "capacity comment repeated"
assert_eq "$(create_count)" "0" "capacity create count after retry"
finish

echo "active agents on a second page count toward the cap"
setup
story_issue
printf '4\n' >"${STATE}/active_count"
: >"${STATE}/split_pages"
run_dispatch
assert_status 0
assert_eq "$(create_count)" "0" "paged capacity create count"
grep -q 'cursor=p2' "${STATE}/curl.log" || fail "did not follow nextCursor"
finish

echo "an extra idle page does not consume capacity"
setup
story_issue
printf '3\n' >"${STATE}/active_count"
: >"${STATE}/split_pages"
run_dispatch
assert_status 0
assert_eq "$(create_count)" "1" "three active still launches"
finish

echo "running label is idempotent"
setup
put_issue 281 "Already going" "Body." open '["cursor:ready","cursor:running","type: story"]'
run_dispatch
assert_status 0
assert_eq "$(create_count)" "0" "running create count"
assert_eq "$(labels_of 281)" '["cursor:running","type: story"]' "running labels"
assert_eq "$(comment_count)" "0" "running should not comment again"
finish

echo "prior agent url is idempotent"
setup
story_issue
printf '%s\n' '["See https://cursor.com/agents/bc-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]' >"${STATE}/comments/281.json"
run_dispatch
assert_status 0
assert_eq "$(create_count)" "0" "url idempotency create count"
assert_eq "$(labels_of 281)" '["cursor:running","type: story"]' "url idempotency labels"
finish

echo "create failure marks the issue failed without leaking the key"
setup
story_issue
printf '500\n' >"${STATE}/create_code"
long_error="${SECRET}$(printf 'x%.0s' {1..2000})${SECRET}"
jq -n --arg error "$long_error" '{error: $error}' >"${STATE}/create_error.json"
run_dispatch
assert_status 1
assert_eq "$(labels_of 281)" '["cursor:failed","type: story"]' "create failure labels"
comments_text | grep -q 'HTTP 500' || fail "missing http status"
comments_text | grep -q '\[REDACTED\]' || fail "secret was not redacted"
grep -q "$SECRET" "${STATE}/comments/281.json" "${STATE}/stdout" "${STATE}/stderr" && fail "secret leaked on failure"
finish

echo "list failure marks the issue failed and does not create"
setup
story_issue
cat >"${BIN}/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
outfile=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) outfile="$2"; shift 2 ;;
    --max-time | --retry | --retry-delay | -H | -w | -X | -u | --data-binary) shift 2 ;;
    *) shift ;;
  esac
done
printf '%s' '{"error":"unavailable"}' >"$outfile"
printf '503'
EOF
chmod +x "${BIN}/curl"
run_dispatch
assert_status 1
assert_eq "$(labels_of 281)" '["cursor:failed","type: story"]' "list failure labels"
[[ ! -f "${STATE}/last_create.json" ]] || fail "create was called after list failure"
finish

echo "closed issues are skipped"
setup
put_issue 281 "Done" "Body." closed '["cursor:ready","type: story"]'
run_dispatch
assert_status 0
assert_eq "$(create_count)" "0" "closed create count"
assert_eq "$(labels_of 281)" '["type: story"]' "closed labels"
finish

echo "schedule drains oldest queued issue first and stops when full"
setup
export EVENT_NAME="schedule"
unset ISSUE_NUMBER
put_issue 11 "Older" "First." open '["cursor:queued","type: task"]'
put_issue 10 "Newer" "Second." open '["cursor:queued","Story"]'
jq -n '[{number:10,createdAt:"2026-09-28T00:00:00Z"},{number:11,createdAt:"2026-09-27T00:00:00Z"}]' >"${STATE}/queued.json"
printf '3\n' >"${STATE}/active_count"
run_dispatch
assert_status 0
assert_eq "$(create_count)" "1" "drain create count"
jq -r '.prompt.text' "${STATE}/last_create.json" | grep -q 'Issue: #11' || fail "did not launch the oldest issue"
assert_eq "$(labels_of 11)" '["cursor:running","type: task"]' "oldest launched"
assert_eq "$(labels_of 10)" '["Story","cursor:queued"]' "newer stayed queued"
finish

echo "schedule continues past a blocked issue"
setup
export EVENT_NAME="schedule"
unset ISSUE_NUMBER
put_issue 11 "Blocked" "Wait." open '["cursor:queued","type: story"]'
put_issue 10 "Free" "Go." open '["cursor:queued","type: story"]'
jq -n '[{number:11,createdAt:"2026-09-27T00:00:00Z"},{number:10,createdAt:"2026-09-28T00:00:00Z"}]' >"${STATE}/queued.json"
mkdir -p "${STATE}/blockers"
printf '%s\n' '[{"number":50,"state":"open"}]' >"${STATE}/blockers/11.json"
run_dispatch
assert_status 0
assert_eq "$(create_count)" "1" "blocked drain create count"
jq -r '.prompt.text' "${STATE}/last_create.json" | grep -q 'Issue: #10' || fail "did not skip the blocked issue"
assert_eq "$(labels_of 11)" '["cursor:queued","type: story"]' "blocked stayed queued"
finish

echo "workflow contract"
grep -q 'types: \[labeled\]' "$WORKFLOW" || fail "missing labeled trigger"
grep -q 'cron: "\*/15 \* \* \* \*"' "$WORKFLOW" || fail "missing cron"
grep -q 'issues: write' "$WORKFLOW" || fail "missing issues permission"
grep -q 'contents: read' "$WORKFLOW" || fail "missing contents permission"
grep -q 'secrets.CURSOR_API_KEY' "$WORKFLOW" || fail "missing api key secret reference"
grep -q 'secrets.GITHUB_TOKEN' "$WORKFLOW" || fail "missing github token"
grep -q 'cursor:ready' "$WORKFLOW" || fail "missing ready label gate"
if grep -E 'CURSOR_API_KEY: [^$]' "$WORKFLOW"; then
  fail "workflow contains a raw API key assignment"
fi
if grep -Eq 'gh pr merge|pulls/.*/merge' "$SCRIPT" "$WORKFLOW"; then
  fail "dispatcher contains a merge operation"
fi
grep -q 'autoCreatePR: true' "$SCRIPT" || fail "script does not request a pull request"
grep -q 'MAX_ACTIVE_AGENTS=4' "$SCRIPT" || fail "script does not cap active agents at 4"
grep -q 'includeArchived=false' "$SCRIPT" || fail "script does not exclude archived agents"

echo "all dispatcher checks passed"
