# mcp-hpc-tool-contracts

## Purpose
Define the requirements for an implemented tool-contracts layer that compiles
domain-level adapter parameters into `RunSpec` payloads and executes them via
`mcp-hpc-runner`.

## Requirements

### Requirement: Tool-contracts exposes a stable adapter registry
The system MUST expose a stable set of adapter identifiers and definitions that
callers can list and invoke.

The initial implemented adapter ids MUST include:

- `hhblits`
- `chai_fold`
- `alphafold3`
- `colabfold`
- `fpocket`
- `tunnels`
- `vina`

#### Scenario: External tool-contract service can invoke the runner
- **WHEN** a caller selects an adapter and provides adapter parameters
- **THEN** the tool-contracts layer compiles a `RunSpec` and can invoke `mcp-hpc-runner` without the runner requiring tool-specific logic

### Requirement: Adapter parameters are JSON-serializable and schema-described
Each adapter MUST define an input schema (JSON-schema-like) that describes its
required and optional parameters.

#### Scenario: Caller validates inputs before compile
- **WHEN** a caller lists adapters
- **THEN** it can inspect the schema and construct a valid parameter object

### Requirement: Tool-contracts compiles adapter params into a runner-valid RunSpec
The system MUST compile adapter parameters into a JSON `RunSpec` that passes
`mcp-hpc-runner` validation, including:

- argv-only commands (no shell snippet tokens)
- relative staging paths for `inputs[*].remote_path`
- relative output paths for `expected_outputs[*].path` and `success_checks[*].path`

#### Scenario: Compile rejects shell interpolation
- **WHEN** an adapter attempts to emit a command token containing shell control snippets (for example `&&`, `||`, `;`, `` ` ``, `$(`)
- **THEN** the compile step fails with a validation error

### Requirement: Invocation mode selection is deterministic and recorded
For tools with multiple invocation backends, the tool-contracts layer MUST
select one invocation mode deterministically from configuration (cluster
profile) and MUST record the selected mode in metadata.

Supported invocation modes are:

- `wrapper` (calls `/opt/tools/...` entrypoints)
- `sif` (calls apptainer SIF images under `~/containers`)
- `spack` (calls a Spack-installed binary; implemented for `hhblits`)
- `native` (calls a PATH binary directly)

The selected mode MUST be recorded under:

- `RunSpec.metadata.tool_contract.selected_mode`

#### Scenario: Cluster config forces wrapper mode
- **WHEN** a cluster profile config sets `adapters.<adapter_id>.mode = "wrapper"`
- **THEN** the compiled RunSpec uses wrapper entrypoints and records `"wrapper"` as the selected mode

### Requirement: SIF invocations enforce the shared bind policy
For `sif` tools, tool-contracts MUST build commands that honor the runner's
shared bind policy:

- remote `work/` is bound to `/work`
- remote `out/` is bound to `/out`
- remote `tmp/` is bound to `/tmp`

Adapters MUST address staged inputs under `/work/...` (or `/out/...` when
explicitly staged to `out`) and MUST write artifacts only under `/out/...`.

#### Scenario: fpocket stages input to out for stable output placement
- **WHEN** the `fpocket` adapter compiles a run
- **THEN** it stages the input PDB to `out/` (not `work/`) so that fpocket's
  side-by-side output directory lands under the fetched output root

### Requirement: Tool-contracts exposes CLI and MCP surfaces
The system MUST expose:

- a CLI that can `list-adapters`, `compile`, `run`, and `serve`
- an MCP stdio server surface exposing one tool per adapter id (tool name equals adapter id)

The MCP tool schemas MUST include execution control fields:

- `_execute` (default true): compile-only when false
- `_async` (default false): use `job.submit` instead of `exec.run`
- `_wait` (default false): for async runs, optionally poll and fetch artifacts on completion

#### Scenario: Adapter returns local artifact locations
- **WHEN** a tool run completes and artifacts are fetched by the runner
- **THEN** the tool-contracts layer returns a structured result containing:
  - the compiled `RunSpec`
  - the runner's `RunResult` / submission envelope
  - normalized artifact references (remote path -> local path)
  - adapter metadata sufficient to reproduce the invocation
