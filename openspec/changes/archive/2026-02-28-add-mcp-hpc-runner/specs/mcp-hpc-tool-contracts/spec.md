## ADDED Requirements

### Requirement: Contract layer integration interface is reserved
The system SHALL define a stable integration interface for a future “tool contracts” layer that compiles domain-level parameters into RunSpecs and invokes `mcp-hpc-runner`.

This capability does NOT require implementing any concrete per-tool adapters in this change.

#### Scenario: External tool-contract service can invoke the runner
- **WHEN** an external component produces a RunSpec for a specific tool
- **THEN** it can submit that RunSpec to `mcp-hpc-runner` without the runner requiring tool-specific logic

### Requirement: Tool-contract implementations can apply deterministic invocation precedence
For tools with multiple invocation modes, a tool-contract implementation MUST apply deterministic precedence:

1. `/opt/tools` wrapper (if available and smoke-check passes)
2. SIF container invocation under the shared bind policy
3. Spack/native fallback

The tool-contract implementation MUST record which mode was selected and why any fallback occurred.

#### Scenario: Wrapper missing triggers SIF fallback
- **WHEN** a wrapper entrypoint is unavailable or fails a smoke check
- **THEN** the adapter selects the SIF invocation and includes the fallback reason in the run metadata

### Requirement: Container adapters enforce the shared bind policy
For SIF tools, a tool-contract implementation MUST ensure inputs are addressed as `/work/...` or `/db/...` and outputs are written only under `/out/...` with temporary files under `/tmp`.

#### Scenario: SIF run writes outputs under /out
- **WHEN** an adapter executes a SIF tool
- **THEN** the adapter’s RunSpec targets outputs only under the remote output directory that is bound to `/out`

### Requirement: Adapters return normalized outputs and paths
Adapters MUST return structured outputs that reference local fetched artifacts (when outputs are staged back) and include the run metadata necessary to reproduce the invocation.

#### Scenario: Adapter returns local artifact locations
- **WHEN** a tool run completes and artifacts are fetched
- **THEN** the adapter returns local paths for the fetched artifacts and the remote run reference
