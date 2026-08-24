# resident-teammate-product-loop Specification

## Purpose
定义官方 Distribution 从 Session 创建、异步 workspace readiness、消息入队、显式 runtime drain、协作真状态到重启恢复的常驻队友产品闭环。
## Requirements
### Requirement: Fresh Session enters one explicit asynchronous readiness lifecycle
The product SHALL atomically create a canonical Session, master Agent, reserved workspace generation, pending exact-generation authority lease and durable provisioning intent without waiting for external workspace provisioning. The public lifecycle MUST distinguish `provisioning`, `ready` and `blocked`, and only `ready` MAY admit resident runtime work.

#### Scenario: Create a fresh Session
- **WHEN** an authorized client creates a Session against a configured Distribution
- **THEN** the Host commits the Session and exact provisioning identities, returns `provisioning`, and performs no runtime drain or synchronous external clone

#### Scenario: Provisioning becomes ready
- **WHEN** the bounded provisioning worker settles the selected Adapter receipt with current claim and generation fences
- **THEN** the Kernel atomically activates the runtime binding and exact-generation authority lease and projects `ready`

#### Scenario: Provisioning is blocked
- **WHEN** the selected Adapter returns a typed failure or dispatch-in-doubt receipt
- **THEN** the product projects `blocked` with safe failure and reconciliation facts and does not select another Adapter or automatically redispatch

### Requirement: Message admission and runtime execution remain separate product commands
`POST /v3/sessions/{session_id}/messages` SHALL only persist the user message, inbox delivery, workflow authority and wakeup signal. `POST /v3/sessions/{session_id}/runtime/drain` SHALL remain the explicit bounded scheduler/runtime command, and neither command MAY infer Task completion.

#### Scenario: Send a message to a ready master
- **WHEN** a client posts one valid message to a ready Session
- **THEN** the response identifies durable message/signal/authority records, states `runtime_executed=false`, and no Adapter turn has run

#### Scenario: Send a message before readiness
- **WHEN** a client posts a message while the target workspace is `provisioning` or `blocked`
- **THEN** admission fails with the exact readiness identity and no message, signal, workflow binding or fallback mutation is committed

#### Scenario: Drain explicit work
- **WHEN** a client submits an authorized bounded runtime drain command
- **THEN** the durable runtime worker advances at most the admitted bounds and reports command status independently from the message request

### Requirement: Resident collaboration truth and transcript are durable and recoverable
Tasks, lanes, agents, delegation, inbox, approvals, workspace identity, runtime signals, user/assistant/tool conversation, workflow authority, failures and events SHALL be canonical ControlStore truth. Adapter outcomes, prompt text, UI state and workspace files MUST NOT replace these owners.

#### Scenario: Assistant replies after explicit drain
- **WHEN** a bounded runtime turn returns assistant and tool messages
- **THEN** the Kernel atomically persists the full outcome, ordered transcript and any failure before marking the signal terminal

#### Scenario: Agent ends a turn without finishing a Task
- **WHEN** a turn becomes idle, waits, reaches a step limit or returns a tool result without `task.finish`
- **THEN** the Task remains non-terminal and its owner/lifecycle are unchanged

#### Scenario: Restart the Distribution
- **WHEN** the process retires and restarts on the same file-backed Store and workspace roots
- **THEN** Session readiness, workflow authority, transcript and collaboration projections recover with the same canonical identities and no replayed external effect

### Requirement: Standard and EnzymeDesign provide executable non-live product closure
Both official Distributions SHALL own executable Host launchers and fresh non-live resident-teammate acceptance tests. The acceptance claim MUST be scoped to the mounted non-live composition and MUST NOT imply real provider, HPC, deployment or scientific-report readiness.

#### Scenario: Qualify Standard from fresh roots
- **WHEN** the Standard E2E uses a deterministic fake runtime and temporary file-backed roots
- **THEN** it closes create, provision, message, explicit drain, assistant transcript and restart recovery without optional Plugin or network effects

#### Scenario: Qualify EnzymeDesign from fresh roots
- **WHEN** the EnzymeDesign E2E mounts its declared Plugin bundle with recording substitutes
- **THEN** it closes the same product loop plus role-scoped direct/deferred tool behavior without a real external call

#### Scenario: A non-live test attempts a live effect
- **WHEN** a provider, network, SSH, Slurm, browser or undeclared subprocess path is attempted during product acceptance
- **THEN** the deny guard fails the test and no qualification success is recorded
