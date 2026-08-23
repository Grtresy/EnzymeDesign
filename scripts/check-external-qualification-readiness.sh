#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ "$#" -gt 1 ]]; then
  echo "usage: $0 [report-path]" >&2
  exit 2
fi

if [[ "$#" -eq 1 ]]; then
  report_path="$1"
else
  evidence_root="$(mktemp -d "${TMPDIR:-/tmp}/openzyme-external-readiness.XXXXXX")"
  report_path="$evidence_root/readiness-report.json"
fi

unset OPENAI_API_KEY
unset OPENZYME_LLM_API_KEY
unset TAVILY_API_KEY
unset MICU_API_KEY
unset SSH_AUTH_SOCK
unset SSH_AGENT_PID
unset OPENZYME_HPC_RUNNER_CONFIG
unset HPC_RUNNER_CONFIG
unset OPENZYME_TEST_ENABLE_LIVE_LLM
unset OPENZYME_TEST_ENABLE_LIVE_TAVILY
unset OPENZYME_TEST_ENABLE_LIVE_HPC
unset OPENZYME_TEST_ENABLE_LIVE_E2E
unset OPENZYME_TEST_ENABLE_SEEDED_LIVE_SMOKE
export OPENZYME_ALLOW_LIVE=0
export OPENZYME_LOAD_ENV_FILES=0

uv run pytest \
  packages/openzyme-contracts/tests/test_external_qualification.py \
  packages/openzyme-contracts/tests/test_external_route_qualification.py \
  packages/enzymedesign-distribution/tests/test_external_qualification.py \
  packages/enzymedesign-distribution/tests/test_qualification_planning.py \
  packages/enzymedesign-distribution/tests/test_qualification_operator_state.py \
  packages/enzymedesign-distribution/tests/test_qualification_bridges.py \
  packages/enzymedesign-distribution/tests/test_owner_qualification_bridges.py \
  packages/enzymedesign-distribution/tests/test_qualification_runtime.py \
  packages/enzymedesign-distribution/tests/test_qualification_admission.py \
  packages/enzymedesign-distribution/tests/test_qualification_ci_boundary.py \
  packages/openzyme-store-sqlite/tests/test_external_qualification_ledger.py \
  packages/openzyme-process-podman/tests/test_qualification_images.py \
  packages/openzyme-workspace-git-lfs/tests/test_qualification_preparation.py \
  packages/openzyme-hpc/tests/test_qualification.py \
  packages/openzyme-hpc-ssh/tests/test_qualification_identity_observation.py \
  packages/openzyme-runtime-llm/tests/test_qualification_bridge.py \
  packages/openzyme-research-tavily/tests/test_qualification_bridge.py \
  packages/enzymedesign-bio-provider-adapters/tests/test_qualification_bridge.py \
  -q
uv run python scripts/verify-external-qualification-readiness.py "$report_path"
