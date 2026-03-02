## Tasks

### 1) Create change record

- [x] Add change artifacts under `openspec/changes/align-mcp-hpc-specs/` (`proposal.md`, `design.md`, `tasks.md`, `.openspec.yaml`).

### 2) Update OpenSpec specs

- [x] Update `openspec/specs/mcp-hpc-tool-contracts/spec.md` to describe the implemented tool-contracts layer (adapters, compile/run surfaces, metadata requirements).
- [x] Update `openspec/specs/mcp-hpc-runner/spec.md` to include:
  - [x] `inputs[*].stage_to` contract (`work|out`)
  - [x] preflight behavior and `preflight_manifest.json`

### 3) Update runner documentation

- [x] Update `apps/mcp-hpc-runner/docs/mcp-hpc-tool-contracts-interface.md` to reflect the current (not future) boundary.
- [x] Update `apps/mcp-hpc-runner/README.md` “Integration Boundary” section to reference the in-repo tool-contracts implementation.

### 4) Verify

- [x] `apps/mcp-hpc-runner`: run unit tests (skip integration).
- [x] `apps/mcp-hpc-tool-contracts`: run unit tests (skip integration).

