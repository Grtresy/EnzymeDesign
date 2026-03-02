## Context

Today:

- `mcp-hpc-runner` enforces a concrete RunSpec contract (argv-only commands, relative paths, `stage_to`, expected outputs, success checks).
- `mcp-hpc-runner` runs a remote **preflight** step after staging inputs and before execution/submission, and writes a `preflight_manifest.json` to the local artifact store.
- `mcp-hpc-tool-contracts` is already implemented and exposes:
  - adapter registry (fixed adapter ids)
  - compile (params -> RunSpec)
  - run (sync via `exec.run`, async via `job.*`)
  - MCP stdio server surface (tool name == adapter id)

The OpenSpec specs currently understate this reality (especially `mcp-hpc-tool-contracts`).

## Decisions

### 1) Specs are updated to match code, not the other way around (in this change)

- Decision: Align specs and docs to current behavior; do not modify runtime logic.
- Rationale: This is a hygiene change that reduces ambiguity and unlocks future work.

### 2) Tool-contract invocation selection is described as config-driven (current behavior)

- Decision: Specify that tool-contracts selects an invocation mode deterministically from a cluster profile / configuration and records it in metadata.
- Rationale: The current implementation does not perform runtime wrapper viability smoke-checks or automatic fallback chains. Spec must not require non-existent behavior.

### 3) Runner preflight becomes explicit contract

- Decision: Add a runner requirement for preflight checks, including the `metadata.tool_contract.preflight_hints` schema used by tool-contracts.
- Rationale: Preflight is a real, user-visible behavior (fails early; produces manifests) and should be captured in the spec.

## Spec Content To Add (Summary)

- `RunSpec.inputs[*].stage_to`: `work|out` target staging.
- Preflight:
  - when it runs (after upload, before execution/submission)
  - what it checks (entrypoint, bind paths, staged inputs, output dir)
  - what it writes (`preflight_manifest.json`) and failure behavior.

## Risks / Trade-offs

- Specs become more detailed and therefore create more compatibility obligations. This is intentional: the code already behaves this way.

