# sandbox-host-authority

## Purpose
Define the typed sandbox-to-Host ownership boundary, process-lifetime authority handoff, independently fenced mutation authority, and bounded read-only runtime settlement projection.

## Requirements

### Requirement: Sandbox Host calls carry one explicit owner authority
Every sandbox-to-Host call MUST use a typed `SandboxHostCallContext` containing a thread-owned repository connection and exactly one closed owner authority: session turn, sandbox process, durable execution, or continuation delivery. Session lease, execution lease/fence, continuation delivery lease/fence, and mutation-writer authority MUST remain distinct fields and MUST NOT be inferred from a bound engine, ambient callback, optional repository override, process id, or another authority type.

#### Scenario: Open a sandbox-process Host context
- **WHEN** a control server starts for an exact sandbox run and process epoch
- **THEN** the Host opens a thread-owned repository connection and a sandbox-process context without attaching the originating session lease

#### Scenario: Reject mixed authority
- **WHEN** a caller attempts to construct one Host context with both session-turn and durable-execution ownership or with mismatched session identities
- **THEN** context construction fails before any canonical read, write, provider call, or runner call

#### Scenario: Fence an expired session context
- **WHEN** a session-turn Host context uses a released or superseded session lease
- **THEN** its canonical write is rejected and the Host does not silently retry under sandbox-process or execution authority

### Requirement: The typed gateway is the only engine-facing sandbox callback boundary
The control server MUST invoke a typed `SandboxHostGateway` with its current `SandboxHostCallContext`. Adapter execution and HPC output fetch MUST bind engine repository access to that supplied context. The production path MUST NOT choose authority through reflected bound methods, `Callable[..., ...]`, two competing repository-scope factories, or an optional `Any` repository parameter.

#### Scenario: Fetch through the process context
- **WHEN** an attached sandbox calls `hpc.fetch_outputs`
- **THEN** the gateway reads and publishes through the exact sandbox-process context supplied by the control server

#### Scenario: Omit the Host context
- **WHEN** production code attempts to invoke a gateway operation without an explicit Host context
- **THEN** the call is rejected by the typed interface rather than falling back to engine creation-time repositories

#### Scenario: Durable worker invokes an adapter
- **WHEN** a durable execution worker calls the same engine adapter implementation
- **THEN** it supplies a durable-execution context whose execution identity matches the controlled-operation write fence

### Requirement: Process authority survives continuation delivery without transfer
An attached sandbox control-server context MUST remain owned by the same sandbox run and process epoch while the process parks and resumes. Continuation delivery MUST use its independent delivery authority only to verify and deliver the immutable result; it MUST NOT transfer its repositories, lease, fence, or mutation authority into the resumed process and MUST NOT restore the originating session lease.

#### Scenario: Resume and make another Host call
- **WHEN** a continuation result is delivered to a matching attached process and the resumed code makes another SDK call
- **THEN** the new call uses the unchanged sandbox-process Host context and not the expired agent-turn or completed delivery authority

#### Scenario: Deliver to a different epoch
- **WHEN** continuation delivery targets a process epoch different from the context bound to the control server
- **THEN** delivery fails closed and no later Host call is authorized through that mismatch

### Requirement: Mutation authority is explicit and independently fenced
Every canonical mutation made during a sandbox Host call MUST be covered by an explicitly registered mutation writer appropriate to the resource category. A sandbox-process writer MAY open bounded child artifact-publisher writers, but a valid mutation writer MUST NOT substitute for a session, execution, or continuation fence, and those fences MUST NOT substitute for mutation authority.

#### Scenario: Publish fetched artifacts
- **WHEN** `hpc.fetch_outputs` materializes declared outputs
- **THEN** publication occurs under a bounded child artifact-publisher writer derived from the active sandbox-process writer

#### Scenario: Mutation scope freezes after process context creation
- **WHEN** the current mutation generation is fenced before a later sandbox callback commits
- **THEN** the commit is rejected even if the sandbox process identity and any other owner authority remain valid

### Requirement: Runtime barrier is bounded and read-only
The Host MUST provide a bounded runtime barrier projection derived from existing canonical session, task, signal, runtime-command, controlled-operation execution, continuation, sandbox-run, and mutation-writer state. The projection MUST use closed blocker codes, bounded counts, and a readiness fact. Reading it MUST NOT acquire owner authority, persist barrier state, drain runtime work, dispatch an effect, resolve an approval, or change task status.

#### Scenario: Observe a parked task
- **WHEN** a task has a nonterminal durable execution or continuation
- **THEN** the projection reports a stable non-ready blocker and bounded active counts without mutating that work

#### Scenario: Observe a settled session
- **WHEN** no relevant runtime owner or task suspension remains and the canonical terminal conditions are satisfied
- **THEN** the projection reports ready from current facts without creating a completion or campaign decision record

#### Scenario: Poll repeatedly
- **WHEN** a campaign or operator reads the same barrier projection repeatedly
- **THEN** all canonical row versions and authority records remain unchanged
