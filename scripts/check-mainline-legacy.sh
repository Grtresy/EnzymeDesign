#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$repo_root"

echo "LEGACY ROLLBACK COMPARISON ONLY: direct invocation is never current authority; use scripts/check-mainline.sh for the current gate." >&2

qualification_tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/openzyme-v3-premerge-legacy.XXXXXX")"
trap 'rm -rf -- "$qualification_tmp_root"' EXIT

uv run ruff check apps packages
uv run ruff check scripts/audit-v3-compat-callers.py
uv run python scripts/audit-v3-compat-callers.py --summary
./scripts/check-v3-architecture-qualification.sh \
  premerge_subset \
  "$qualification_tmp_root/report"
uv run pytest -m "not integration and not live_llm and not live_tavily and not live_hpc and not live_e2e and not quality_eval"
(
  cd apps/openzyme-web-ui
  npm test
  npm run build
)

echo "LEGACY ROLLBACK COMPARISON COMPLETE: this result is not a current mainline result or optimized receipt." >&2
