#!/usr/bin/env bash
# Sourced preflight guards for governed PROD workflows.
# On failure, print one GitHub annotation and append that same line to
# $GITHUB_STEP_SUMMARY when it is set, then exit 1. On success, print
# "ok <name>" and do not echo the compared value.
#
# Callers must pass only digests, SHAs, refs, counts, flags, or pending
# migration JSON. Never pass tokens, keys, or other secret material.
#
#   guard_eq <name> <expected> <actual> <remediation>
#   guard_ne <name> <unexpected> <actual> <remediation>
#   guard_gt <name> <threshold> <actual> <remediation>   # actual -gt threshold
#   guard_true <name> <actual> <remediation>             # actual == true
#   guard_nonempty <name> <actual> <remediation>         # test -n
#   guard_one_of <name> <actual> <remediation> <allowed...>

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  printf '%s\n' "source scripts/ci/guard.sh from a workflow step" >&2
  exit 1
fi

_guard_one_line() {
  local value="$1"
  value="${value//%/%25}"
  value="${value//$'\r'/%0D}"
  value="${value//$'\n'/%0A}"
  printf '%s' "$value"
}

_guard_ok() {
  printf 'ok %s\n' "$1"
}

_guard_fail() {
  local name="$1"
  local expected="$2"
  local received="$3"
  local remediation="$4"
  local line
  line="$(
    printf '::error title=%s::expected=%s received=%s remediation=%s' \
      "$(_guard_one_line "$name")" \
      "$(_guard_one_line "$expected")" \
      "$(_guard_one_line "$received")" \
      "$(_guard_one_line "$remediation")"
  )"
  printf '%s\n' "$line"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf '%s\n' "$line" >>"${GITHUB_STEP_SUMMARY}"
  fi
  exit 1
}

guard_eq() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  local remediation="$4"
  if [[ "$actual" == "$expected" ]]; then
    _guard_ok "$name"
    return 0
  fi
  _guard_fail "$name" "$expected" "$actual" "$remediation"
}

guard_ne() {
  local name="$1"
  local unexpected="$2"
  local actual="$3"
  local remediation="$4"
  if [[ "$actual" != "$unexpected" ]]; then
    _guard_ok "$name"
    return 0
  fi
  _guard_fail "$name" "!= ${unexpected}" "$actual" "$remediation"
}

guard_gt() {
  local name="$1"
  local threshold="$2"
  local actual="$3"
  local remediation="$4"
  if [[ "$actual" =~ ^[0-9]+$ && "$threshold" =~ ^[0-9]+$ ]]; then
    if ((actual > threshold)); then
      _guard_ok "$name"
      return 0
    fi
  fi
  _guard_fail "$name" "> ${threshold}" "$actual" "$remediation"
}

guard_true() {
  local name="$1"
  local actual="$2"
  local remediation="$3"
  if [[ "$actual" == "true" ]]; then
    _guard_ok "$name"
    return 0
  fi
  _guard_fail "$name" "true" "$actual" "$remediation"
}

guard_nonempty() {
  local name="$1"
  local actual="$2"
  local remediation="$3"
  if [[ -n "$actual" ]]; then
    _guard_ok "$name"
    return 0
  fi
  _guard_fail "$name" "non-empty" "" "$remediation"
}

guard_one_of() {
  local name="$1"
  local actual="$2"
  local remediation="$3"
  shift 3
  local candidate
  for candidate in "$@"; do
    if [[ "$actual" == "$candidate" ]]; then
      _guard_ok "$name"
      return 0
    fi
  done
  local allowed=""
  for candidate in "$@"; do
    if [[ -n "$allowed" ]]; then
      allowed+=" | "
    fi
    allowed+="$candidate"
  done
  _guard_fail "$name" "$allowed" "$actual" "$remediation"
}
