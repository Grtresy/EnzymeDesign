## 1. Shared host runtime extraction

- [x] 1.1 Create `packages/enzyme-host-runtime/pyproject.toml` and package skeleton for shared host services
- [x] 1.2 Move or copy reusable workspace, plan, execution, memory, and reporting modules out of `apps/enzyme-host-cli` into `packages/enzyme-host-runtime`
- [x] 1.3 Define typed runtime service entrypoints for project loading, episode creation, plan confirmation, plan execution, status lookup, run lookup, and report generation
- [x] 1.4 Refactor `apps/enzyme-host-cli` to depend on `enzyme-host-runtime` so CLI command handlers become thin wrappers over shared services

## 2. Mixed-plan execution routing

- [x] 2.1 Introduce a shared step-executor interface that routes preprocess tools and HPC/domain tools to different backends
- [x] 2.2 Implement a local preprocess executor for `convert_format`, `smiles_to_3d`, `prepare_receptor`, and `prepare_ligand`
- [x] 2.3 Extend the existing execution path to keep using `mcp-hpc-tool-contracts` for supported HPC/domain adapters
- [x] 2.4 Normalize preprocess and HPC execution results into one canonical run manifest envelope, including stable local `run_id` generation for preprocess steps
- [x] 2.5 Update resume and step-selection logic so mixed-plan runs skip completed steps consistently across CLI and Web initiated runs

## 3. Web Host app and browser surface

- [x] 3.1 Create `apps/enzyme-web-host/pyproject.toml` and app skeleton with a local HTTP entrypoint
- [x] 3.2 Implement project-loading and active-episode views that read canonical workspace state through `enzyme-host-runtime`
- [x] 3.3 Implement browser actions for new episode, plan confirm/import, run full plan, run selected step, and resume
- [x] 3.4 Implement browser status, recent runs, run detail, and report panels backed by shared runtime services
- [x] 3.5 Add minimal page styling and interaction flow so the Web Host works on desktop and laptop-sized browser windows without relying on a Node build pipeline

## 4. Testing and verification

- [x] 4.1 Add unit tests for `enzyme-host-runtime` service APIs and canonical state behavior
- [x] 4.2 Add mixed-plan execution tests using fake preprocess and tool-contract executors
- [x] 4.3 Add Web Host integration tests covering project load, episode creation, plan confirmation, run trigger, status refresh, and report access
- [x] 4.4 Run targeted test suites for `enzyme-host-cli`, `enzyme-host-runtime`, and `enzyme-web-host`
- [x] 4.5 Run `openspec validate add-web-chat-host`

## 5. Documentation and operator workflow

- [x] 5.1 Add `apps/enzyme-web-host/README.md` with startup, project-root binding, and local development instructions
- [x] 5.2 Update root or Host-facing docs to explain that Web is now the main MVP entrypoint and CLI remains the debug/automation surface
- [x] 5.3 Document the mixed-plan routing rule so preprocess and HPC steps are authored with the expected tool ids
