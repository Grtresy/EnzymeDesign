## ADDED Requirements

### Requirement: Tool-contract layer covers the MVP adapter set
The system SHALL provide concrete tool-contract implementations for the MVP tool chain (hhblits, chai_fold, alphafold3, colabfold, fpocket, tunnels, vina) that compile parameters into `RunSpec` and invoke `mcp-hpc-runner`.

#### Scenario: MVP tool contracts compile to RunSpec
- **WHEN** a caller requests compilation for one of the MVP tools
- **THEN** the tool-contract layer returns a validated `RunSpec` that can be submitted to `mcp-hpc-runner`

## MODIFIED Requirements

### Requirement: Contract layer integration interface is reserved
The system SHALL define a stable integration interface for a tool-contracts layer that compiles domain-level parameters into RunSpecs and invokes `mcp-hpc-runner`.

This capability MUST support implementing concrete per-tool adapters without requiring tool-specific logic in the runner.

#### Scenario: External tool-contract service can invoke the runner
- **WHEN** an external component produces a RunSpec for a specific tool
- **THEN** it can submit that RunSpec to `mcp-hpc-runner` without the runner requiring tool-specific logic
