## ADDED Requirements

### Requirement: Host runtime exposes reusable application services for multiple host surfaces
The system MUST expose typed application-service operations for project loading, episode lifecycle management, plan confirmation, plan execution, status inspection, run lookup, and report materialization so that both CLI and Web Host surfaces can reuse the same orchestration semantics.

These shared runtime services MUST operate on canonical workspace state and MUST be callable without parsing CLI stdout or invoking shell commands as an integration boundary.

#### Scenario: Web Host creates an episode through shared runtime services
- **WHEN** the Web Chat Host requests creation of a new episode for an initialized project
- **THEN** the shared host runtime creates the episode using the same canonical workspace layout and state semantics used by the CLI
- **THEN** a later CLI invocation resolves and inspects that episode without any surface-specific migration step

## MODIFIED Requirements

### Requirement: Host runtime uses project memory as the canonical state source
The host runtime MUST persist and read episode goal, state, plan, run manifests, and report metadata through the `mcp-project-memory` data contract instead of maintaining a separate host-owned state model.

Commands and browser actions that confirm or inspect plans and state MUST observe the same canonical files and resource mappings used by `mcp-project-memory`.

Neither the CLI nor the Web Chat Host MAY maintain a divergent surface-specific copy of episode plan, run, or report state outside the canonical project workspace.

#### Scenario: Confirmed plan from the Web Host is visible to the CLI through canonical resources
- **WHEN** a user confirms a structured plan for the current episode through the Web Chat Host
- **THEN** the plan is persisted in the canonical episode plan location used by `mcp-project-memory`
- **THEN** a subsequent CLI read of the corresponding project/episode plan observes the same plan content and metadata

### Requirement: Host runtime executes confirmed plan steps through tool contracts
The system MUST expose shared plan-execution logic that loads the confirmed plan for the active episode, executes steps in order, and records resulting run manifests and execution state back into the project workspace for both CLI and Web Host initiated runs.

The runtime MUST support:

- executing the whole plan in order
- selecting a specific step
- resuming from previously completed steps
- deterministically routing each step to the correct execution backend

Execution routing MUST follow these rules:

- steps for `convert_format`, `smiles_to_3d`, `prepare_receptor`, and `prepare_ligand` MUST execute through the local preprocess adapter
- steps for HPC/domain tool adapters such as `fpocket`, `hhblits`, `chai_fold`, `colabfold`, `alphafold3`, `tunnels`, and `vina` MUST execute through `mcp-hpc-tool-contracts`

If no confirmed plan exists for the active episode, the command or browser action MUST fail with a validation error before submitting any work.

#### Scenario: Mixed plan execution records canonical lineage across preprocess and HPC steps
- **WHEN** a user runs a confirmed plan that contains `prepare_receptor` followed by `vina`
- **THEN** the runtime executes the preprocess step through the local preprocess adapter and the docking step through `mcp-hpc-tool-contracts`
- **THEN** the resulting step status, output references, and run/manifest lineage are recorded in canonical episode state in one consistent format

#### Scenario: Resume behavior is consistent across CLI and Web surfaces
- **WHEN** a user starts plan execution in the Web Chat Host and later resumes from the CLI after earlier steps already completed successfully
- **THEN** the shared runtime does not resubmit completed steps
- **THEN** execution continues from the first incomplete or failed step according to persisted episode state and run manifests
