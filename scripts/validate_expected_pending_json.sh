#!/usr/bin/env bash
# Fail closed before a protected workflow uses expected_pending_json.
# Callers that omit the optional input must skip this script; an empty string
# is not a reviewed empty array.
set -euo pipefail

raw="${EXPECTED_PENDING_JSON-}"
expected="a JSON array of strings, or a JSON array of objects with string values (reviewed migrations use version, filename, and sha256). An empty array is allowed."
hint="Shell quoting probably stripped the quotes. Dispatch with a JSON payload file: gh api repos/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/workflows/<file>/dispatches --input payload.json"

fail() {
  printf '%s\n' "expected_pending_json validation failed" >&2
  printf 'expected: %s\n' "$expected" >&2
  printf 'received: %s\n' "$raw" >&2
  printf 'hint: %s\n' "$hint" >&2
  exit 1
}

if [ -z "$raw" ]; then
  fail
fi

# jq -e rejects non-JSON, non-arrays, and elements that are neither strings nor
# objects of strings. -c is the normalized value later steps already compare.
filter='
  if type == "array"
    and all(
      .[];
      type == "string" or (type == "object" and all(.[]; type == "string"))
    )
  then .
  else empty
  end
'
if ! normalized="$(printf '%s' "$raw" | jq -e -c "$filter")"; then
  fail
fi

printf '%s\n' "$normalized"
