## ADDED Requirements

### Requirement: Web Chat Host resumes project and episode context in the browser
The system MUST provide a browser-based Host entrypoint that loads an initialized Enzyme project workspace, resolves the current episode, and presents the active project context without requiring the user to inspect workspace files manually.

The Web Chat Host MUST show at least:

- current project identity
- current episode identity and goal
- confirmed plan summary when present
- recent runs for the active episode

#### Scenario: Opening an existing project restores the active episode context
- **WHEN** a user opens the Web Chat Host for a project that already has an active episode
- **THEN** the browser UI shows the current project, current episode, goal, and latest confirmed plan status from canonical workspace state
- **THEN** the user can continue from the previously active episode without using `enzyme status`

### Requirement: Web Chat Host can drive the host workflow through shared runtime services
The system MUST let the browser Host create or switch episodes, confirm plans, and trigger plan execution by calling shared host runtime services rather than shelling out to CLI commands or reimplementing orchestration logic in the frontend.

The MVP browser action surface MUST include:

- create a new episode from a goal
- import or confirm a structured plan for the active episode
- run the full confirmed plan, a selected step, or a resume action

#### Scenario: Browser user confirms a plan and starts execution
- **WHEN** a user confirms a structured plan for the active episode in the Web Chat Host and clicks run
- **THEN** the Host calls the shared runtime service boundary to persist the plan and start execution
- **THEN** the same canonical episode state and run manifests become visible to other Host surfaces

### Requirement: Web Chat Host visualizes execution state and report artifacts
The system MUST provide browser panels for active episode status, recent runs, run details, and the generated episode report so the user can inspect progress and outputs without manually browsing the project workspace.

The MVP inspection surface MUST include:

- active episode status summary
- recent run list with step id and status
- run detail view with manifest-derived metadata and log references
- report view or download entry for the current episode

#### Scenario: Browser user reviews run progress and report output
- **WHEN** an episode has recorded runs and a generated report
- **THEN** the Web Chat Host shows the latest run statuses and lets the user open the current report artifact from the browser UI
- **THEN** the information shown matches the canonical state and report produced by the shared runtime
