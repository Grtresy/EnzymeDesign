## ADDED Requirements

### Requirement: Public projection exposes resident-teammate readiness and transcript truth
The current `file_workspace_public@2` envelope SHALL project versioned inner facts for Session/workspace readiness, provisioning blocker, workflow authority, tool exposure, runtime commands and ordered user/assistant/tool transcript. Every projected failure reference MUST resolve to a public-safe canonical `FailureObservation`.

#### Scenario: Inspect a provisioning Session
- **WHEN** the master workspace intent is pending or claimed
- **THEN** the workspace projection reports `provisioning`, exact generation/intent identity and no fabricated runtime binding

#### Scenario: Inspect a completed assistant turn
- **WHEN** a runtime outcome has been settled
- **THEN** conversation shows the ordered user, assistant and tool messages and runtime shows the matching outcome/command identities

#### Scenario: Inspect a blocked Session
- **WHEN** provisioning, workflow admission or runtime settlement is blocked
- **THEN** projection includes safe code, effect/mutation/fallback facts, retry/reconcile policy and `diagnostic_id`

#### Scenario: Inspect reconciled readiness without rewriting history
- **WHEN** a durable provisioning reconciliation proves the reserved generation ready
- **THEN** `workspace_provisioning_public@2` reports effective readiness `ready`, exact intent state version and safe reconciliation identity/receipt facts while the original intent still reports its historical blocked failure

### Requirement: Public mutations preserve message and drain separation
The Host API SHALL keep message admission, runtime drain admission, runtime command polling and approval decisions as separate exact operations. Response payloads MUST state whether runtime or Task mutation occurred and MUST bind current release/projection identities.

#### Scenario: Post a message
- **WHEN** an exact compatible client posts a message
- **THEN** the response reports durable message/signal/workflow authority identities with `runtime_executed=false`

#### Scenario: Submit a drain
- **WHEN** a client posts a bounded runtime drain command
- **THEN** the response reports an accepted command identity and never keeps the HTTP request as owner of long work

#### Scenario: Decide an approval
- **WHEN** an authorized human resolves a pending approval
- **THEN** the Host persists the decision and schedules exact linked work without synchronously executing the Agent

#### Scenario: Admit explicit provisioning reconciliation
- **WHEN** an operator posts exact Session, intent digest/state-version and claim identities to `/workspace/provisioning/reconcile`
- **THEN** Host returns `202` for only that durable observation occurrence and does not provision, drain, create a Task, redispatch or choose another Adapter

#### Scenario: Admit an explicit successor generation
- **WHEN** an operator posts one exact diagnosed failed intent and resolved reconciliation identity to `/workspace/provisioning/successor`
- **THEN** Host returns `202` for a new monotonic reservation/intent and preserves every historical failed and reconciliation occurrence

### Requirement: CLI is a thin complete collaboration client
The Host CLI SHALL remain an HTTP-only client while providing commands/rendering for Session readiness, conversation, tasks, agents/delegations/inbox, approvals, failures, explicit runtime drain and runtime command status. It MUST NOT import Store, Kernel, Adapter or provider implementations.

#### Scenario: Wait for readiness
- **WHEN** an operator inspects a newly created Session
- **THEN** CLI renders `provisioning`, `ready` or `blocked` plus safe next action from Host projection

#### Scenario: Read assistant transcript
- **WHEN** an explicit drain settles an assistant response
- **THEN** CLI renders the canonical transcript rather than local command stdout as product truth

#### Scenario: Inspect a runtime command
- **WHEN** the prefer window expires before drain completion
- **THEN** CLI can poll the exact Session-scoped command identity without resubmitting the drain

#### Scenario: Recover provisioning from the CLI
- **WHEN** projection exposes `reconcile_workspace_provisioning` or `create_successor_workspace_generation`
- **THEN** CLI submits the exact projected intent digest/state-version and optional resolved reconciliation identity, rejects caller/projection drift and reinspects canonical state instead of claiming local success

### Requirement: Web UI renders and controls the resident-teammate loop
The Web UI SHALL render canonical readiness, transcript, task board, delegation/inbox, agents, approvals, workspace, runtime command and failure facts from the verified Host projection. It MAY derive a browser-local projection-change observation from two exact contract-, release- and projection-digest-verified Host projections, but MUST label that observation as local and MUST NOT claim it is a Host outbox or canonical Kernel event stream. User actions SHALL call Host APIs and reconcile the returned projection; browser state MUST NOT claim success independently.

#### Scenario: Session is still provisioning
- **WHEN** the UI opens a fresh Session
- **THEN** message execution controls remain unavailable and readiness/blocker facts are visible

#### Scenario: User sends and drains
- **WHEN** the Session is ready and the user sends a message then explicitly drains
- **THEN** UI shows the queued state before drain and the canonical assistant transcript after settlement

#### Scenario: Approval is pending
- **WHEN** runtime waits for approval
- **THEN** UI shows the exact pending approval and a human decision schedules, but does not impersonate, Agent work

#### Scenario: Projection facts change after polling
- **WHEN** the UI verifies a newer exact Host projection for the same Session
- **THEN** it may show a local projection-change observation bound to the previous and current projection digests, and does not label that observation as canonical Host or Kernel event truth

### Requirement: Legacy and drifted resident state fails closed
The public envelope MAY remain `file_workspace_public@2`, but current clients SHALL require the new inner schema/digest identities for resident runtime. A Session missing provisioning, workflow, exposure or transcript settlement identity MUST return a structured incompatibility; clients MUST NOT synthesize defaults or seed state directly.

#### Scenario: Open an old Session without workflow authority
- **WHEN** current client requests resident runtime for a legacy Session lacking exact binding/link records
- **THEN** Host returns `resident_teammate_state_incompatible` with no runtime/provider effect

#### Scenario: Projection changes between read and mutation
- **WHEN** readiness, workflow epoch, capability binding or exposure digest changes after a client read
- **THEN** mutation is rejected as stale and the client must refresh rather than replay against inferred state
