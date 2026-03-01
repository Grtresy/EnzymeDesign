## 1. App Scaffold

- [x] 1.1 Create new `uv` app project `apps/mcp-hpc-tool-contracts` with a minimal package layout
- [x] 1.2 Define project metadata (name, entrypoints) and align Python version range with existing apps
- [x] 1.3 Add a small CLI with subcommands: `list-adapters`, `compile`, `run` (optional execution)
- [x] 1.4 Add an MCP stdio server entrypoint that exposes each adapter as an MCP tool

## 2. Core Contracts and Registry

- [x] 2.1 Define adapter ids and a registry API (lookup + list) with stable ordering
- [x] 2.2 Define JSON-serializable parameter schemas per adapter (hhblits/chai_fold/alphafold3/colabfold/fpocket/tunnels/vina)
- [x] 2.3 Implement `RunSpec` compilation helpers that enforce argv-only commands and staging-safe paths
- [x] 2.4 Implement metadata recording for selected invocation mode and fallback chain

## 3. Deterministic Invocation Selection

- [x] 3.1 Implement wrapper viability checks (entrypoint exists + smoke check)
- [x] 3.2 Implement SIF invocation builder enforcing shared bind policy (`/work`, `/out`, `/db`, `/models`, `/tmp`)
- [x] 3.3 Implement spack/native fallback builder where applicable
- [x] 3.4 Implement deterministic precedence selection and attach fallback reasons to `RunSpec.metadata`

## 4. Minimal Adapter Implementations

- [x] 4.1 Implement `hhblits` adapter (query FASTA in, A3M out) with expected outputs + non-empty checks
- [x] 4.2 Implement `chai_fold` adapter with non-empty output-dir checks
- [x] 4.3 Implement `alphafold3` adapter with non-empty output-dir checks
- [x] 4.4 Implement `colabfold` adapter with non-empty output-dir checks
- [x] 4.5 Implement `fpocket` adapter (structure in, pocket artifacts out) with non-empty output-dir checks
- [x] 4.6 Implement `tunnels` adapter with backend selection (Caver vs CaverDock) and backend recorded in metadata
- [x] 4.7 Implement `vina` adapter (receptor + ligand in, docking artifacts out) with non-empty output-dir checks

## 5. Runner Integration

- [x] 5.1 Implement a runner invocation path that submits compiled `RunSpec` to `mcp-hpc-runner` (`exec.run` for sync, `job.*` for async when needed)
- [x] 5.2 Implement an artifact fetch step (`job.fetch_artifacts`) and normalize returned local artifact references
- [x] 5.3 Ensure errors are surfaced with stable error codes (from runner failure mapping) plus adapter metadata

## 6. Tests

- [x] 6.1 Unit tests: each adapter compiles a `RunSpec` that passes `mcp-hpc-runner` validation
- [x] 6.2 Unit tests: deterministic precedence selection and fallback-reason recording
- [x] 6.3 Unit tests: expected outputs and success checks match the adapter contract (file/dir, non-empty, json when applicable)
- [x] 6.4 Doc-drift tests: assert canonical entrypoints for covered tools match `docs/HPC服务器调用指南.md`

## 7. Integration Harness (Opt-in)

- [x] 7.1 Add a small opt-in integration runner that can execute one smoke job per adapter (requires HPC config)
- [x] 7.2 Add integration tests marked/guarded to skip when HPC config is not present

## 8. Documentation

- [x] 8.1 Document how to use the tool-contract CLI to compile and run an adapter through the runner
- [x] 8.2 Update `docs/HPC服务器调用指南.md` to reference the tool-contract layer as the preferred programmatic entrypoint for the covered tools
