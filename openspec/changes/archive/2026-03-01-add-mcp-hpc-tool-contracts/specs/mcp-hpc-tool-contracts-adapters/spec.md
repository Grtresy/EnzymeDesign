# mcp-hpc-tool-contracts-adapters

## Purpose

Define concrete, testable requirements for the initial set of tool adapters that compile domain-level parameters into `RunSpec` and invoke `mcp-hpc-runner` for HPC execution.

## Requirements

### Requirement: Contract layer provides a stable adapter registry
The system MUST expose a stable set of adapter identifiers and parameter schemas so orchestration can request a domain tool without embedding command-line details.

#### Scenario: Tool id resolves to a compiler
- **WHEN** a caller requests adapter id `hhblits`
- **THEN** the system returns a compiler that can validate parameters and produce a JSON-serializable `RunSpec`

### Requirement: Minimal adapter set is implemented
The system MUST implement adapters for the MVP chain:

- `hhblits`
- `chai_fold`
- `alphafold3`
- `colabfold`
- `fpocket`
- `tunnels`
- `vina`

#### Scenario: Adapter list includes the minimal set
- **WHEN** a caller lists available adapters
- **THEN** the returned list includes `hhblits`, `chai_fold`, `alphafold3`, `colabfold`, `fpocket`, `tunnels`, and `vina`

### Requirement: Adapters compile RunSpec with staging-safe paths
Each adapter MUST compile a `RunSpec` that:

- uses argv tokens only (no shell interpolation)
- stages any local inputs using relative `inputs.remote_path`
- declares outputs under `out/` using relative `expected_outputs.path`

#### Scenario: Compiled RunSpec passes runner validation
- **WHEN** an adapter compiles a `RunSpec`
- **THEN** `mcp-hpc-runner` RunSpec validation succeeds without modification

### Requirement: hhblits adapter produces an MSA artifact
The `hhblits` adapter MUST accept a query FASTA and produce an A3M MSA artifact under `out/`.

#### Scenario: hhblits compile declares MSA output
- **WHEN** a caller compiles a `hhblits` run with a query FASTA input
- **THEN** the resulting `RunSpec` declares a required, non-empty expected output for the generated MSA file under `out/`

### Requirement: fold backends are separate adapters and produce a non-empty output directory
The fold adapters (`chai_fold`, `alphafold3`, `colabfold`) MUST produce folded-structure artifacts under an output directory in `out/` and MUST declare success checks that ensure the directory is non-empty.

#### Scenario: chai_fold compile declares non-empty output directory
- **WHEN** a caller compiles a `chai_fold` run for an input FASTA
- **THEN** the resulting `RunSpec` declares an expected output directory under `out/` with a `non_empty` success check

#### Scenario: alphafold3 compile declares non-empty output directory
- **WHEN** a caller compiles an `alphafold3` run for a valid AF3 JSON input
- **THEN** the resulting `RunSpec` declares an expected output directory under `out/` with a `non_empty` success check

#### Scenario: colabfold compile declares non-empty output directory
- **WHEN** a caller compiles a `colabfold` run for an input FASTA
- **THEN** the resulting `RunSpec` declares an expected output directory under `out/` with a `non_empty` success check

### Requirement: fpocket adapter produces pocket-detection artifacts
The `fpocket` adapter MUST accept a structure input and produce pocket artifacts under an output directory in `out/`.

#### Scenario: fpocket compile declares pocket output directory
- **WHEN** a caller compiles an `fpocket` run for an input structure
- **THEN** the resulting `RunSpec` declares an expected output directory under `out/` and marks it non-empty

### Requirement: tunnels adapter produces tunnel-analysis artifacts
The `tunnels` adapter MUST accept a structure input (and optional pocket hints) and produce tunnel artifacts under an output directory in `out/`.

The adapter MUST record which backend was selected (for example Caver vs CaverDock) in `RunSpec.metadata`.

Canonical default on the target cluster:
- Remote image path: `~/containers/caverdock-1.2.sif`
- `mode=detect` uses `caver` (from inside the image)
- `mode=dock` uses `cd-screening` (from inside the image)

#### Scenario: tunnels compile records backend choice
- **WHEN** a caller compiles a `tunnels` run
- **THEN** the resulting `RunSpec.metadata` includes the selected tunnel backend and any fallback reasons

### Requirement: vina adapter produces docking artifacts
The `vina` adapter MUST accept a receptor structure and ligand input and produce docking artifacts under an output directory in `out/`.

#### Scenario: vina compile declares docking output directory
- **WHEN** a caller compiles a `vina` run
- **THEN** the resulting `RunSpec` declares an expected output directory under `out/` and marks it non-empty

### Requirement: Adapter execution returns normalized artifact references
When an adapter executes a compiled `RunSpec` via `mcp-hpc-runner` and artifacts are fetched, the system MUST return structured output that references local fetched artifact paths and includes enough metadata to reproduce the invocation.

#### Scenario: Execution response references local artifacts
- **WHEN** an adapter run completes successfully and artifacts are fetched
- **THEN** the response includes local artifact paths and the `run_id` / remote run reference
