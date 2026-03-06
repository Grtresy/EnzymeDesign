## ADDED Requirements

### Requirement: Host CLI bootstraps a project workspace
The system MUST expose an `enzyme init <name>` command that creates a reusable project workspace for the host runtime.

The initialized workspace MUST include:

- `enzyme.yaml`
- `data/inputs/`
- `data/refs/`
- `episodes/`
- `.enzyme/cli_state.json`

The CLI state file MUST record enough information for later commands to resolve the current project and current episode context.

#### Scenario: Initializing a new project creates the host workspace skeleton
- **WHEN** a user runs `enzyme init demo-project`
- **THEN** the system creates the project directory with the canonical workspace layout and a default `enzyme.yaml`
- **THEN** the system writes `.enzyme/cli_state.json` with no active episode yet

### Requirement: Host CLI manages episode lifecycle and current context
The system MUST expose an `enzyme new-episode "<goal>"` command that creates a new episode directory, stores the user goal, and makes the new episode current for later commands.

Episode ids MUST be allocated deterministically in ascending order within a project so that a later invocation can resume work on the latest episode without ambiguity.

#### Scenario: Creating an episode persists the goal and updates current context
- **WHEN** a user runs `enzyme new-episode "improve binding for substrate X"` inside an initialized project
- **THEN** the system creates the next episode directory under `episodes/`
- **THEN** the episode goal is persisted as canonical episode data
- **THEN** `.enzyme/cli_state.json` is updated so later `enzyme status` and `enzyme run` commands target that episode by default

### Requirement: Host runtime uses project memory as the canonical state source
The host runtime MUST persist and read episode goal, state, plan, run manifests, and report metadata through the `mcp-project-memory` data contract instead of maintaining a separate host-owned state model.

Commands that confirm or inspect plans and state MUST observe the same canonical files and resource mappings used by `mcp-project-memory`.

#### Scenario: Confirmed plan is visible through canonical project memory resources
- **WHEN** a user confirms a structured plan for the current episode through the Host CLI
- **THEN** the plan is persisted in the canonical episode plan location used by `mcp-project-memory`
- **THEN** a subsequent read of the corresponding `enzyme://project/{project_id}/episode/{episode_id}/plan` resource returns the same plan content

### Requirement: Host runtime executes confirmed plan steps through tool contracts
The system MUST expose an `enzyme run` command that loads the confirmed plan for the active episode, executes steps through `mcp-hpc-tool-contracts`, and records resulting run manifests and execution state back into the project workspace.

The runtime MUST support:

- executing the whole plan in order
- selecting a specific step with `--step`
- resuming from previously completed steps with `--resume`

If no confirmed plan exists for the active episode, the command MUST fail with a validation error before submitting any work.

#### Scenario: Running a confirmed step records lineage and updates episode state
- **WHEN** a user runs `enzyme run --step dock_1` for an episode with a confirmed plan
- **THEN** the host runtime invokes the corresponding tool-contract execution for that step
- **THEN** the resulting `run_id`, execution status, and manifest location are recorded in the canonical project workspace
- **THEN** the episode state reflects that the step has been submitted, completed, or failed

#### Scenario: Resume skips completed steps
- **WHEN** a user runs `enzyme run --resume` for an episode where earlier steps already completed successfully
- **THEN** the host runtime does not resubmit completed steps
- **THEN** the runtime continues from the first incomplete or failed step according to the persisted episode state and run manifests

### Requirement: Host CLI exposes only the minimal inspection commands needed for workflow closure
The system MUST expose CLI commands that let a user inspect the active episode and its execution outputs without manually browsing the workspace.

The MVP inspection surface MUST include:

- `enzyme status`
- `enzyme logs <run_id>`
- `enzyme report`

#### Scenario: Status summarizes the active episode from canonical state
- **WHEN** a user runs `enzyme status`
- **THEN** the system reports the current project, current episode, latest confirmed plan status, and recent runs using data from the canonical workspace state

#### Scenario: Report materializes an episode summary file
- **WHEN** a user runs `enzyme report` for an episode with at least one recorded run
- **THEN** the system generates or updates a report artifact for that episode
- **THEN** the report includes references to the episode goal, plan, and recorded runs so the episode can be reviewed without manually reconstructing lineage
