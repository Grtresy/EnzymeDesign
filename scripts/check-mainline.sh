#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$repo_root"

case "$#" in
  0)
    mode_args=(--workers 4)
    ;;
  1)
    if [[ "$1" != "--forced-serial" ]]; then
      echo "usage: $0 [--forced-serial]" >&2
      exit 2
    fi
    mode_args=(--forced-serial)
    ;;
  *)
    echo "usage: $0 [--forced-serial]" >&2
    exit 2
    ;;
esac

evidence_parent="$(mktemp -d "${TMPDIR:-/tmp}/openzyme-mainline-authoritative.XXXXXX")"
evidence_root="$evidence_parent/evidence"

echo "CURRENT AUTHORITY: scripts/check-mainline.sh is the complete non-live merge gate." >&2
echo "NO OTHER AUTHORITY: this command is not architecture admission, AOX launch, live-campaign, or scientific evidence." >&2
echo "AUTHORITATIVE EVIDENCE ROOT: $evidence_root" >&2
echo "ROLLBACK COMPARISON: ./scripts/check-mainline-legacy.sh (never current authority when invoked directly)." >&2

uv run python scripts/run-test-gate.py \
  mainline_authoritative \
  "$evidence_root" \
  "${mode_args[@]}"
uv run python scripts/run-test-gate.py \
  verify-mainline-authoritative \
  "$evidence_root"

echo "CURRENT NON-LIVE MERGE AUTHORITY VERIFIED: $evidence_root" >&2
