## Why

The repository has working implementations of:

- `apps/mcp-hpc-runner`: a RunSpec-driven runner that executes via SSH or Slurm and stages artifacts.
- `apps/mcp-hpc-tool-contracts`: a concrete tool-contracts layer that compiles adapter parameters into RunSpecs and invokes the runner.

However, the OpenSpec specs and some runner documentation still describe `mcp-hpc-tool-contracts` as a future/reserved capability. This drift makes it unclear which behaviors are required, which are implemented, and which are planned.

## What Changes

- Update OpenSpec specs to match the current implementation:
  - `openspec/specs/mcp-hpc-tool-contracts/spec.md`: from “reserved future interface” to “implemented tool-contracts layer”.
  - `openspec/specs/mcp-hpc-runner/spec.md`: explicitly include implemented RunSpec contract details that are currently missing in the spec (input `stage_to`, and preflight behavior).
- Update runner-facing documentation to stop describing tool-contracts as “future/reserved” and document the current boundary.

## Non-Goals

- Do not change runtime behavior or implement new features (for example, automatic wrapper viability/smoke-check and fallback selection).
- Do not expand the adapter set beyond what already exists in code.

## Impact

- Documentation/spec-only change that makes the spec-driven workflow coherent again.
- Enables future spec-driven iterations to build on a correct baseline.

