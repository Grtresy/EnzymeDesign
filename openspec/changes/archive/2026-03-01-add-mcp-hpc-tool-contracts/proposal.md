## Why

Today, HPC tool invocation policy lives in `docs/HPC服务器调用指南.md` and ad-hoc scripts, which makes runs hard to reproduce, hard to test, and brittle when wrappers/containers/fallbacks change. We need a deterministic “tool contracts” layer so orchestration can request domain tools (hhblits/chai_fold/alphafold3/colabfold/fpocket/tunnels/vina) without re-encoding HPC-specific details.

## What Changes

- Add a concrete `mcp-hpc-tool-contracts` service/library that compiles tool-level parameters into `RunSpec` and invokes `mcp-hpc-runner`, and exposes an MCP stdio server surface.
- Implement the minimal tool adapter set for the enzyme evaluator MVP: `hhblits`, `chai_fold`, `alphafold3`, `colabfold`, `fpocket`, `tunnels` (Caver/CaverDock), and `vina`.
- Enforce deterministic invocation precedence per tool: `/opt/tools` wrapper -> SIF container (shared bind policy) -> Spack/native fallback; record the selected mode and fallback reasons in metadata.
- Standardize success checks and failure signature mapping for these tools, so upstream agents can programmatically triage failures.

## Capabilities

### New Capabilities

- `mcp-hpc-tool-contracts-adapters`: Concrete tool adapters (hhblits/chai_fold/alphafold3/colabfold/fpocket/tunnels/vina) that compile inputs/resources/expected outputs/success checks into `RunSpec` and return normalized artifact references.

### Modified Capabilities

- `mcp-hpc-tool-contracts`: Upgrade the existing reserved spec from “interface only” to concrete, testable behavior for the minimal tool set, including deterministic precedence and required metadata.

## Impact

- New app/package under `apps/` (tool-contract service) that depends on the runner contracts and invokes `mcp-hpc-runner`.
- Updates to documentation and examples to route tool runs through the contract layer rather than directly calling wrappers/containers.
- New unit tests for adapter compilation rules and a small opt-in integration harness (requires reachable HPC config).
