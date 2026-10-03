#!/usr/bin/env bash
# One reviewed bounded container; no service changes, credential exports or ports.
set -euo pipefail
umask 077
relay_dir="$(realpath "${1:?owned relay directory required}")"
mode="${2:?canary or stage required}"
[[ "$relay_dir" =~ ^/var/tmp/atlas-nlcd-relay/[a-f0-9-]{36}$ ]]
test "$(stat -c %a "$relay_dir")" = 700
test "$(stat -c %u "$relay_dir")" = "$(id -u)"
load_state="$(systemctl show oh-lyme-pmc-extraction.service --property=LoadState --value)"
test "$load_state" = loaded
service_state="$(systemctl show oh-lyme-pmc-extraction.service --property=ActiveState --value)"
test "$service_state" = inactive
name="atlas-nlcd-$(cat /proc/sys/kernel/random/uuid)"
image='registry.digitalocean.com/oh-lyme-data/pipeline@sha256:6726f2afcb62e05d745f55a40b55d4257b4c513dea9a3d7ae578a26bcd22ba3c'
mkdir -p "$relay_dir/scratch"
case "$mode" in
  canary)
    seconds=120
    command=(/app/.venv/bin/python -m lyme_gap_atlas_data.spaces_conditional_canary --execute-canary)
    ;;
  stage)
    seconds=1800
    test -f "$relay_dir/capture/capture-receipt.json"
    # $9 reserve includes seven-year marginal storage at current rates and
    # ancillary existing-runtime/CI costs; no new infrastructure is created.
    command=(/app/.venv/bin/python -m lyme_gap_atlas_data.nlcd_storage_staging
      --execute --existing-dev-worker-env --relay-directory /relay/capture
      --manifest /relay/reviewed-code/config/annual-nlcd-2025-staging-manifest.json
      --scratch /relay/scratch --non-transfer-cost-bound-usd 9)
    ;;
  *) exit 2 ;;
esac
cleanup() {
  status=$?
  set +e
  # Only this unpredictable named container, additionally ownership-labelled.
  label="$(docker inspect --format '{{ index .Config.Labels "atlas.nlcd.owner" }}' "$name" 2>/dev/null)"
  if [ "$label" = "$name" ]; then docker kill "$name" >/dev/null 2>&1; fi
  exit "$status"
}
trap cleanup EXIT
# The shell reads no secret values. Docker uses the existing runtime env file
# in place; nothing is copied to the relay folder or laptop.
timeout --signal=TERM --kill-after=10s "$seconds" docker run --rm \
  --name "$name" --label "atlas.nlcd.owner=$name" \
  --cpus=0.5 --memory=512m --pids-limit=64 --network=bridge \
  --env-file /opt/oh-lyme/pmc-runtime.env \
  --mount "type=bind,src=$relay_dir/reviewed-code/src,dst=/proof/src,readonly" \
  --mount "type=bind,src=$relay_dir,dst=/relay" \
  --env PYTHONPATH=/proof/src "$image" "${command[@]}"
