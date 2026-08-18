## ADDED Requirements

### Requirement: Sandbox boundary failures preserve owner and diagnostic identity
Every sandbox-to-Host failure MUST bind the exact `SandboxHostCallContext` owner kind and safe owner identity, operation, phase, effect certainty, retry eligibility and detailed diagnostic identity. Public output MUST redact lease/fencing tokens, credentials, Host paths and private handles. An exception MUST NOT cause the gateway to retry under another owner type, open an ambient repository scope, choose an artifact-era adapter or convert a failed control-plane effect into a native file operation.

#### Scenario: Gateway adapter raises after external invocation
- **WHEN** a durable-execution adapter raises after its runner or publication invocation may have been accepted
- **THEN** the execution retains its exact owner/fence and `dispatch_in_doubt`, records the specific cause, and does not retry under sandbox-process or session-turn authority

#### Scenario: Native file command fails locally
- **WHEN** an executor-native file command fails before any Host control-plane effect
- **THEN** its diagnostic reports the local phase and no Host mutation while preserving the agent's freedom to inspect or replan

## MODIFIED Requirements

### Requirement: The typed gateway is the only engine-facing sandbox callback boundary
The control server MUST invoke a typed `SandboxHostGateway` with its current `SandboxHostCallContext` for every control-plane read, canonical mutation, publication, scientific adoption/finalization or workspace-job operation. Native file, Git and ordinary network actions MAY run directly inside the exact agent workspace under capsule process policy and MUST NOT be routed through an artifact/materialization gateway. Production code MUST NOT choose Host authority through reflected bound methods, `Callable[..., ...]`, competing repository-scope factories, optional `Any` repositories, legacy artifact callbacks or a failure fallback.

#### Scenario: Publish through the process context
- **WHEN** an attached sandbox explicitly requests publication of its exact clean workspace revision
- **THEN** the gateway validates and writes publication intent through the same sandbox-process context and independently fenced mutation authority

#### Scenario: Use native file and network tools
- **WHEN** the agent edits, inspects, downloads or transfers private bytes without changing shared product truth
- **THEN** the capsule performs those actions natively in the owning workspace and does not create an artifact record or Host callback authority

#### Scenario: Omit the Host context for a control-plane effect
- **WHEN** production code attempts publication, scientific adoption or workspace-job admission without an explicit Host context
- **THEN** the typed interface rejects the call rather than using engine creation-time repositories or converting it into a native action

#### Scenario: Durable worker invokes an external-job adapter
- **WHEN** a durable execution worker calls the workspace revision runner adapter
- **THEN** it supplies a durable-execution context whose execution identity and fence match the controlled-operation write

### Requirement: Mutation authority is explicit and independently fenced
Every canonical mutation made during a sandbox Host call MUST be covered by an explicitly registered mutation writer appropriate to the current file/revision/publication/job/scientific resource category. Native private workspace file or Git operations MUST NOT silently become canonical mutations. A valid mutation writer MUST NOT substitute for session, sandbox-process, durable-execution or continuation-delivery ownership, and those owner fences MUST NOT substitute for mutation authority. No bounded child writer or failure path MAY use an artifact-publisher category.

#### Scenario: Create a publication intent
- **WHEN** an agent explicitly publishes a clean exact revision
- **THEN** the Host records publication intent and its controlled effect under the matching process owner and publication mutation scope

#### Scenario: Perform a private native transfer
- **WHEN** an agent downloads bytes into its private workspace
- **THEN** no canonical mutation writer is created until a later explicit publication, scientific adoption or other product operation

#### Scenario: Mutation scope freezes after process context creation
- **WHEN** the current mutation generation is fenced before a later sandbox callback commits
- **THEN** the commit is rejected with a detailed authority diagnostic even if process identity and another owner authority remain valid
