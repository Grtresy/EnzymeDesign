## ADDED Requirements

### Requirement: Per-tool command contract schema
The manual SHALL define a standardized command contract schema for every documented tool that includes purpose, prerequisites, required inputs, optional inputs, output artifacts, and success criteria.

#### Scenario: Reader locates mandatory call fields
- **WHEN** a reader opens any tool usage section
- **THEN** the section follows the same contract structure and clearly marks required versus optional fields

### Requirement: Input and output format specification
The command contract MUST define input and output formats in machine-actionable terms, including file type expectations, required path structure, and produced artifact naming conventions.

#### Scenario: Reader prepares valid input set
- **WHEN** a reader follows the contract for a tool invocation
- **THEN** the documented input formats and output targets are sufficient to run the command without guessing path or format conventions

### Requirement: Failure and diagnostics guidance
Each command contract SHALL document common failure signals and minimum diagnostic checks that confirm whether execution succeeded or requires retry.

#### Scenario: Reader handles command failure
- **WHEN** a tool command returns an error or incomplete output
- **THEN** the manual provides defined checks that identify likely cause categories and next diagnostic actions
