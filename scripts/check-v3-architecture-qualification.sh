#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 {diagnostic|premerge_subset|admission} /absolute/new/output-directory" >&2
  exit 2
fi

mode=$1
output_dir=$2
case "$mode" in
  diagnostic|premerge_subset|admission) ;;
  *)
    echo "unknown qualification mode: $mode" >&2
    exit 2
    ;;
esac

if [[ "$output_dir" != /* ]]; then
  echo "qualification output directory must be absolute" >&2
  exit 2
fi

unset OPENAI_API_KEY TAVILY_API_KEY MICU_API_KEY SSH_AUTH_SOCK SSH_AGENT_PID
unset OPENZYME_RUN_LIVE OPENZYME_RUN_AOX OPENZYME_LIVE_E2E OPENZYME_LIVE_HPC
export OPENZYME_ARCHITECTURE_QUALIFICATION=1
export OPENZYME_LOAD_ENV_FILES=0
export PYTHONDONTWRITEBYTECODE=1

exec uv run python scripts/v3_architecture_qualification.py \
  "$mode" \
  --output-dir "$output_dir"
