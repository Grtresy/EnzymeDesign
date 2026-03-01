## Context

The repo already contains a stable execution layer, `apps/mcp-hpc-runner`, that accepts a JSON `RunSpec` and executes it via `ssh` or Slurm (`sbatch`), including staging and normalized envelopes (`RunResult` / `JobStatus`).

However, tool invocation policy currently lives primarily as human-facing documentation (`docs/HPC服务器调用指南.md`) and ad-hoc scripts. This mixes “domain intent” (run hhblits, fold a structure, detect pockets, analyze tunnels, dock ligand) with “execution mechanics” (wrapper vs container vs spack, bind policies, staging paths, success checks, and failure signatures). The result is brittle orchestration and hard-to-test behavior.

This change introduces a concrete tool-contract layer that compiles tool-specific parameters into `RunSpec` and invokes `mcp-hpc-runner`, starting with a minimal tool chain: hhblits, chai_fold, alphafold3, colabfold, fpocket, tunnels (Caver/CaverDock), and vina.

Constraints:
- Commands must be argv-based (no shell interpolation).
- Container tools must honor the shared bind policy (address inputs under `/work` or `/db`, write outputs only under `/out`, temp under `/tmp`).
- Deterministic invocation precedence is required: `/opt/tools` wrapper -> SIF -> Spack/native.
- The selected invocation mode and fallback reasons must be recorded in metadata for reproducibility and debugging.

## Goals / Non-Goals

**Goals:**
- Provide a tool-contract API that takes domain parameters and produces a fully validated `RunSpec` (command, resources, inputs, expected outputs, success checks, failure signatures, metadata).
- Provide concrete adapters for the minimal MVP chain: `hhblits`, `chai_fold`, `alphafold3`, `colabfold`, `fpocket`, `tunnels`, `vina`.
- Ensure deterministic invocation selection with explicit, machine-readable “why this mode” metadata.
- Make adapter behavior unit-testable without requiring an HPC cluster.
- Enable end-to-end execution by invoking `mcp-hpc-runner` with the compiled `RunSpec`.

**Non-Goals:**
- Implement the full enzyme evaluator workflow (`enzyme.*`) in this change.
- Cover the entire `HPC-tool-catalog` in v1; only the minimal set is required.
- Rebuild or replace `mcp-hpc-runner` execution semantics (unless gaps are discovered during integration).
- Solve cluster provisioning, database distribution/mounting, or secrets management beyond existing runner safeguards.

## Decisions

### 1) Deliver as a dedicated app with a thin “compile + call runner” surface

Create a new `apps/mcp-hpc-tool-contracts` Python project. Internally it exposes:

- A library API (pure functions / small classes) that compiles tool parameters into `RunSpec`.
- A small CLI for debugging (list adapters, compile a RunSpec, optionally execute by calling the runner).
- An MCP stdio server surface that exposes each adapter as a tool for orchestrators.

Rationale: keeping compilation logic pure makes it easy to test deterministically, while the CLI provides a bridge for integration testing and operator debugging.

Alternative considered: embedding tool adapters directly into `mcp-hpc-runner`. Rejected because it couples “tool knowledge” into the execution layer and defeats the stated integration boundary.

### 2) Adapter registry + per-tool parameter schemas

Implement a registry keyed by tool id (for example: `hhblits`, `chai_fold`, `alphafold3`, `colabfold`, `fpocket`, `tunnels`, `vina`). Each adapter:

- Accepts a typed parameter object (validated; JSON-serializable)
- Produces a `RunSpec` plus a small “adapter result” envelope including:
  - selected invocation mode (`wrapper` | `sif` | `spack` | `native`)
  - fallback chain and reasons
  - normalized artifact descriptors (what outputs should exist and where they will be fetched locally)

Rationale: a registry prevents “stringly-typed” orchestration and gives a single place to add future tools.

### 3) Deterministic invocation selection uses the manual’s precedence rules

Invocation selection is deterministic and recorded:

1. `/opt/tools` wrapper (if entrypoint exists and a lightweight smoke check passes)
2. SIF invocation with the shared bind policy
3. Spack/native fallback

Each adapter defines:
- Its wrapper entrypoint(s)
- Its SIF image + entrypoint (or `apptainer run/exec` form)
- Its spack/native entrypoint (if any)
- A smoke-check command (fast, low-resource) used only for “is this mode viable?”

Rationale: consistent, testable selection logic avoids per-call randomness and reduces operational ambiguity.

### 4) Paths and staging conventions align with runner contracts

Adapters MUST target paths that match the runner’s remote directory contract:

- Inputs stage under `<remote_run_dir>/work/...` and are addressed as `/work/...` in container contexts.
- Outputs write under `<remote_run_dir>/out/...` and are addressed as `/out/...` in container contexts.
- Temporary files use `<remote_run_dir>/tmp/...` and `/tmp/...` in container contexts.

Rationale: the runner already enforces staging rules and output fetch from `out/`; contracts should not invent new conventions.

### 5) Success checks and failure signatures are first-class per tool

Each adapter defines:
- Declared `expected_outputs` (files/dirs)
- `success_checks` (exists/non-empty/parseable-json where applicable)
- `failure_signatures` (regex -> stable error code) for known tool failures

Rationale: upstream agents should not parse free-form stderr to understand failures.

### 6) Tunnels is modeled as a domain tool with detect/dock modes

The `tunnels` adapter is a single domain tool with a small intent-focused schema:

```ts
{
  mode: "detect" | "dock";
  backend?: string;
}
```

Defaults:
- `mode=detect` -> Caver
- `mode=dock` -> CaverDock

Canonical backend on the target cluster is the `~/containers/caverdock-1.2.sif` image (remote HPC home directory; runs are submitted via `mcp-hpc-runner`):
- `mode=detect` uses the `caver` command from inside the image
- `mode=dock` uses the `cd-screening` command from inside the image

The adapter records selected backend plus any fallback chain/reasons in metadata.

Rationale: callers ask for the intent (tunnel detection vs docking) and should not need to know cluster-specific packaging details; metadata preserves reproducibility.

### 7) Fold backends are separate domain tools from day one

Provide distinct adapters and tool ids:
- `chai_fold`
- `alphafold3`
- `colabfold`

Rationale: their parameter schemas and resource strategies already diverge; forcing a single `fold` schema would either explode optional fields or hide important controls.

## Risks / Trade-offs

- [Tool entrypoints drift from the manual] -> Add tests that assert the adapter’s canonical entrypoints match `docs/HPC服务器调用指南.md` for the covered tools; keep adapter config centralized.
- [Caver vs CaverDock ambiguity] -> Model tunnels as a domain tool with multiple concrete backends; record selected backend and reasons in metadata.
- [HPC-specific failures are diverse] -> Start with a small set of high-signal failure signatures; add iteratively with real run telemetry.
- [Calling the runner introduces coupling] -> Keep the runner boundary at `RunSpec` + normalized envelopes; avoid importing runner internals beyond shared models.

## Migration Plan

1. Land the tool-contract app with compile-only unit tests (no HPC required).
2. Add an opt-in integration harness that runs a small smoke job per tool via `mcp-hpc-runner` (requires reachable HPC config).
3. Update docs/examples to prefer tool-contract usage for the covered tools.

Rollback: disable/ignore the tool-contract app and call the runner directly with manually authored `RunSpec`.

## Open Questions

Resolved:
- `mcp-hpc-tool-contracts` directly exposes an MCP stdio server surface.
- `fold` is split into separate domain tools (`chai_fold`, `alphafold3`, `colabfold`) from day one.
- `tunnels` canonical backend is the remote `~/containers/caverdock-1.2.sif` image (per `docs/HPC服务器调用指南.md`), using `caver` for `mode=detect` and `cd-screening` for `mode=dock`.

Still open:
- Define the exact argument-level contracts and expected artifacts for `caver` (detect) runs so the adapter can declare stable outputs and success checks.
