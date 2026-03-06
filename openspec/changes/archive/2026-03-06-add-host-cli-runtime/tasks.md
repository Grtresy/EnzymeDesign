## 1. App skeleton and CLI entrypoint

- [x] 1.1 Create `apps/enzyme-host-cli/pyproject.toml` with the `enzyme` console entrypoint and workspace dependencies
- [x] 1.2 Create `apps/enzyme-host-cli/src/enzyme_host_cli/__init__.py` and `cli.py`
- [x] 1.3 Add initial command parsing for the MVP command surface: `init`, `new-episode`, `plan confirm/import`, `run`, `status`, `logs`, and `report`
- [x] 1.4 Add a README describing the MVP command surface and local development workflow

## 2. Workspace and canonical state integration

- [x] 2.1 Implement workspace helpers for locating the project root and creating `enzyme.yaml`, `data/`, `episodes/`, and `.enzyme/cli_state.json`
- [x] 2.2 Implement deterministic episode id allocation and current-episode tracking in `.enzyme/cli_state.json`
- [x] 2.3 Implement a memory client layer that reads and writes canonical goal, state, and plan data using the `mcp-project-memory` contract
- [x] 2.4 Wire `enzyme init`, `enzyme new-episode`, and `enzyme plan confirm/import` to the workspace and memory layers without introducing a second host-owned state model

## 3. Plan execution runtime

- [x] 3.1 Implement plan loading and validation for the active episode, including errors when no confirmed plan exists
- [x] 3.2 Implement step selection for full-plan execution, `--step`, and `--resume`
- [x] 3.3 Implement the execution adapter that invokes `mcp-hpc-tool-contracts` and captures submission/result envelopes
- [x] 3.4 Persist run manifests, step status, and lineage references back into canonical episode state after each step

## 4. Inspection and reporting commands

- [x] 4.1 Implement `enzyme status` using canonical project and episode state
- [x] 4.2 Implement `enzyme logs <run_id>` to resolve a run and surface stored log paths or manifest references
- [x] 4.3 Implement `enzyme report` to materialize a lightweight Markdown summary with goal, plan, run, and artifact references

## 5. Tests and verification

- [x] 5.1 Add unit tests for workspace helpers, episode allocation, and CLI state management
- [x] 5.2 Add tests for plan confirmation, execution selection, and `--resume` behavior using fake or mocked tool-contract clients
- [x] 5.3 Add end-to-end CLI fixture tests covering `enzyme init` through `enzyme run` on a local sample project
- [x] 5.4 Run targeted test suites and `openspec validate add-host-cli-runtime`
