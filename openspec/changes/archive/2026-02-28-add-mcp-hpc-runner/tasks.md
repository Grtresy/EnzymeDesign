## 1. Project Scaffolding (Language-Agnostic; Recommended: Python + uv)

- [x] 1.1 Bootstrap the runner implementation project (recommended: Python with `uv`) and commit `pyproject.toml` + `uv.lock`
- [x] 1.2 Create an executable MCP server entrypoint and minimal module layout (language-agnostic externally; internal language per 1.1)
- [x] 1.3 Add a local configuration file/template for HPC connection and defaults (ssh host, remote base dir, partitions, GPU flag style)

## 2. Core Data Contracts

- [x] 2.1 Define `RunSpec` (including `execution_mode: ssh|sbatch|auto`, resources, inputs, expected outputs, success checks, failure signatures)
- [x] 2.2 Define `RunResult` / `JobHandle` / `JobStatus` normalized envelopes required by the specs
- [x] 2.3 Implement validation utilities for inputs/outputs (required inputs present, expected outputs checks, non-empty rules)

## 3. Runner: SSH Direct Execution

- [x] 3.1 Implement `exec.run` backend that executes a command via `ssh` with strict quoting and captures stdout/stderr/exit code
- [x] 3.2 Implement optional per-run remote directory creation for ssh runs (to keep logs/artifacts consistent)
- [x] 3.3 Implement ssh-mode staging hooks (skip upload if no inputs; still support upload/download when inputs/outputs are declared)

## 4. Runner: Slurm sbatch Execution

- [x] 4.1 Implement `job.submit` that generates an `sbatch` script and submits with `sbatch --parsable`
- [x] 4.2 Implement `job.status` using `squeue` (running/queued) and `sacct` fallback (completed) when available
- [x] 4.3 Implement `job.logs` retrieval (remote log paths + bounded tail fetch)
- [x] 4.4 Implement `job.cancel` using `scancel` and return normalized cancellation results
- [x] 4.5 Implement `job.fetch_artifacts` that downloads declared outputs and performs success checks

## 5. Staging + Artifact Store

- [x] 5.1 Implement a staging layer using `rsync` over SSH (with `scp` fallback) for upload and download
- [x] 5.2 Implement local artifact store layout per `run_id` (inputs manifest, remote refs, outputs manifest, logs)
- [x] 5.3 Add caching/dedup for staged inputs (hash-based skip) and resumable downloads for large outputs

## 6. Execution Mode Selection + Safety

- [x] 6.1 Implement `auto` mode selection policy (GPU -> sbatch; thresholds for time/mem -> sbatch; otherwise ssh) with override support
- [x] 6.2 Implement redaction and safe logging (avoid leaking credentials; return references for large logs)
- [x] 6.3 Add normalized error mapping from failure signatures into stable error codes

## 7. Reserved Integration Point: Tool Contracts Layer (No Implementation)

- [x] 7.1 Ensure `RunSpec` and result envelopes are stable and documented so a future `mcp-hpc-tool-contracts` service can compile tool-specific parameters into RunSpecs
- [x] 7.2 Add at least one example RunSpec fixture (JSON) demonstrating: SIF bind policy mapping, expected outputs, and failure signature mapping

## 8. MCP Server Surface

- [x] 8.1 Expose MCP tools for `exec.run` and `job.*` lifecycle operations
- [x] 8.2 Ensure responses follow the normalized envelopes defined in specs and include reproducibility metadata

## 9. Tests

- [x] 9.1 Unit tests: RunSpec validation, sbatch script generation, bind-policy path mapping for SIF invocations, failure signature normalization
- [x] 9.2 Unit tests: rsync/scp staging command construction and local artifact store manifest creation
- [x] 9.3 Integration tests (opt-in): ssh-mode smoke (`python3 --version`), sbatch-mode sentinel job writing `/out/success.txt` and fetching it back

## 10. Documentation

- [x] 10.1 Document local setup and required binaries (`ssh`, `rsync`) and HPC requirements (`sbatch/squeue/sacct`, apptainer)
- [x] 10.2 Document the reserved interface for `mcp-hpc-tool-contracts` (what a tool-contract service must provide and how it calls the runner)
- [x] 10.3 (Python path) Document `uv` usage for dev/test (`uv sync`, `uv run pytest`) and how to update locked dependencies
