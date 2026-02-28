## ADDED Requirements

### Requirement: Canonical SIF invocation pattern
The manual MUST define a canonical invocation pattern for SIF-based tools using Apptainer, including bind-mount conventions for inputs, outputs, models, and databases.

#### Scenario: User runs SIF tool with documented binds
- **WHEN** a user executes a documented SIF command for a supported tool
- **THEN** required host paths are bound into the container using the documented path mapping and the tool can access all required resources

### Requirement: Container entrypoint and argument contract
For each SIF tool, the manual SHALL specify the container entrypoint contract, expected positional and optional arguments, and argument-to-artifact mapping.

#### Scenario: User maps arguments to expected artifacts
- **WHEN** a user provides the documented arguments to a SIF-based command
- **THEN** the produced artifacts match the documented output locations and formats

### Requirement: Container execution validation
The manual SHALL define post-run validation checks for SIF-based invocations, including required output artifact existence and minimum log-level success indicators.

#### Scenario: User verifies container execution success
- **WHEN** a SIF command completes
- **THEN** the user can apply the documented validation checks to determine whether the run is successful before downstream workflow steps begin
