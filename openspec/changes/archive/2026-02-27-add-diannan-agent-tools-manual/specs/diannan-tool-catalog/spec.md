## ADDED Requirements

### Requirement: Workflow tool inventory coverage
The documentation system SHALL provide a Diannan tool catalog that includes every tool used by the enzyme-design workflow across Evidence, Prompt, Generator, Evaluator, and Update/HITL stages.

#### Scenario: Complete stage coverage
- **WHEN** a reader checks the catalog by workflow stage
- **THEN** each stage lists at least one available tool and any approved substitutes

### Requirement: Deployment mode classification
Each catalog entry MUST classify how the tool is invoked on Diannan, including whether it is a native/system command, Spack-managed command, `/opt/tools` wrapper, or SIF container invocation.

#### Scenario: Entry exposes invocation mode
- **WHEN** a reader opens a tool entry
- **THEN** the entry explicitly identifies its deployment mode and primary executable path or entrypoint

### Requirement: Tool availability metadata
Each catalog entry SHALL include operational metadata required for execution planning, including required runtime context, expected node type, and last-verified status.

#### Scenario: Reader validates operational readiness
- **WHEN** a reader prepares to run a tool from the catalog
- **THEN** the entry provides enough metadata to decide where and how to execute it without external clarification
