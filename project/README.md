# Snakemake Enzyme Design Pipeline

This directory hosts a Snakemake-based pipeline scaffold for variant scoring. The
`Snakefile` reads `config/config.yaml` and `config/target_spec.yaml`, parses
variants from `inputs/variants.txt`, and produces per-variant score breakdowns
plus a batch leaderboard.

## Layout
- `config/`: pipeline configuration and target specification.
- `inputs/`: input variant list and other raw inputs.
- `runs/`: generated outputs (kept empty in source control).
- `cache/`: temporary/cache artifacts.
- `schemas/`: JSON schema placeholders.
- `scripts/`: helper tooling, including `run_tool.py`.

## Usage
```bash
cd project
snakemake -j 1
```
