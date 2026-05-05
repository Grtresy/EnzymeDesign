## ADDED Requirements

### Requirement: Stage-to-tool selection matrix
The manual SHALL provide a workflow-stage selection matrix that maps each stage of the enzyme-design workflow to primary tools and approved substitutes.

#### Scenario: Reader selects tool for a stage
- **WHEN** a reader needs to execute a specific workflow stage
- **THEN** the matrix identifies a primary tool and at least one acceptable substitute if available

### Requirement: Invocation precedence rules
The selection guide MUST define deterministic precedence rules for choosing among available invocation modes, including `/opt/tools` wrappers, SIF containers, and Spack/native commands.

#### Scenario: Multiple invocation modes exist
- **WHEN** a tool can be run through more than one mode
- **THEN** the reader can apply documented precedence rules to choose the default invocation path

### Requirement: Local and server responsibility boundaries
The guide SHALL document which responsibilities belong to local development environments versus Diannan server execution, including constraints for compute-intensive stages.

#### Scenario: Reader plans execution environment
- **WHEN** a reader plans a run from the manual
- **THEN** the guide indicates which stages are suitable for local execution and which MUST run on server resources
