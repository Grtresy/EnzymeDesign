## 1. Scope and documentation schema

- [x] 1.1 Confirm the final manual location and top-level section structure for catalog, command contracts, container invocation, and selection guide.
- [x] 1.2 Freeze the in-scope Diannan tool set (system/Spack, `/opt/tools`, `/opt/tools_env`, and `~/containers`) and record canonical entrypoints.
- [x] 1.3 Define the standard per-tool command contract fields (purpose, prerequisites, required inputs, optional inputs, outputs, success checks, failure diagnostics).

## 2. Implement diannan-tool-catalog capability

- [x] 2.1 Build a stage-based inventory table covering Evidence, Prompt, Generator, Evaluator, and Update/HITL stages.
- [x] 2.2 Annotate each tool with deployment mode (native, Spack, wrapper, SIF) and executable path or container entrypoint.
- [x] 2.3 Add operational metadata for each tool entry, including runtime context, node expectations, and last-verified status.

## 3. Implement tool-command-contracts capability

- [x] 3.1 Write command contracts for native/Spack tools with explicit input/output format requirements.
- [x] 3.2 Write command contracts for `/opt/tools` wrappers, including positional arguments, optional flags, and output artifact locations.
- [x] 3.3 Add common failure signatures and minimum diagnostic checks for each documented tool family.

## 4. Implement container-tool-invocation capability

- [x] 4.1 Define and document one shared Apptainer bind-mount policy to be used across all SIF workflows.
- [x] 4.2 Document invocation contracts for `caverdock-1.2`, `fpocket`, `hhsuite`, `p2rank_2.5.1`, and `vina` SIF images, including argument-to-output mapping.
- [x] 4.3 Document post-run validation checks for SIF tools, including required output files and log-based success signals.

## 5. Implement workflow-tool-selection-guide capability

- [x] 5.1 Create a stage-to-tool selection matrix with primary choices and approved substitutes per workflow stage.
- [x] 5.2 Document deterministic invocation precedence rules (`/opt/tools` wrappers -> SIF containers -> Spack/native fallback).
- [x] 5.3 Document local-vs-server execution boundaries, keeping `uv` local environments focused on lightweight development and server resources for heavy compute stages.

## 6. Verification and handoff

- [x] 6.1 Run smoke checks for representative commands in each tool tier and record tested versions as strict pins where applicable.
- [x] 6.2 Review the manual against all new spec requirements to confirm every requirement has clear, testable coverage.
- [x] 6.3 Finalize onboarding guidance and maintenance notes so future tool additions must include a command-contract entry.
