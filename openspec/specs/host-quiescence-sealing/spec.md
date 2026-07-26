# host-quiescence-sealing

## Purpose
Define generic Host mutation authority, writer fencing, offline-verifiable quiescence, and monotonic sealing without turning closure evidence into workflow truth.

## Requirements

### Requirement: Host mutation authority is generic and generation-scoped
The Host MUST represent mutation authority as a generic scope with a stable scope identity, scope kind/ref, parent scope, policy and writer-coverage digests, closed lifecycle state, monotonically increasing generation, and mutation fencing token. AOX MAY consume this capability, but the authority MUST NOT be encoded as an AOX-specific task, campaign reducer, browser state, or artifact-tree convention.

#### Scenario: Open a generic mutation scope
- **WHEN** a Host workflow needs an attempt- or session-scoped closure boundary
- **THEN** it creates an `open` mutation scope whose policy, coverage manifest, generation, and fence are persisted before writers register

#### Scenario: Reject an unsupported scope policy
- **WHEN** a caller supplies an unknown scope kind, mutation policy, or writer-coverage manifest
- **THEN** the Host rejects scope admission before any writer receives authority

### Requirement: Every canonical writer is registered and derived from explicit authority
Before writing canonical SQLite rows, durable events, artifacts, reports, ledgers, or other covered state, every asynchronous handler, agent turn, runtime command, sandbox process, controlled-operation worker, callback, and publisher MUST register a writer bound to the exact mutation scope generation and fence. Child writers MUST derive from an active parent or another explicitly authorized root. An incomplete or unknown writer category MUST prevent quiescence proof.

#### Scenario: Register a nested writer
- **WHEN** an authorized runtime-command writer starts a sandbox or controlled-operation child writer
- **THEN** the child record binds the same scope generation, identifies its parent, and is included in the active writer set

#### Scenario: Reject a detached writer
- **WHEN** a thread, task, process, callback, or publisher attempts a covered write without a matching active writer registration
- **THEN** the Host rejects the canonical write and records a private authority diagnostic

#### Scenario: Detect incomplete coverage
- **WHEN** freeze auditing discovers a covered repository or publisher category absent from the scope's coverage manifest
- **THEN** the scope cannot become quiescent or sealed

### Requirement: Freeze closes writer admission before waiting
The Host MUST enter `freezing` through one transaction that increments the mutation fence and closes new writer admission before checking active writers. Existing writers MUST retain only the authority required to retire or commit work allowed by the freeze policy; stale-generation writers and all new registrations MUST be rejected. Session-scoped writer selection, nested-parent validation, and writer registration MUST share one atomic ordering against freeze and follow-up scope creation. The Host MUST distinguish expected zero-open or closed-during-registration coordination from ambiguous open-scope cardinality through a closed typed reason without weakening the fence.

#### Scenario: Begin freeze
- **WHEN** an authorized owner requests closure of an open scope
- **THEN** the Host atomically records `freezing`, advances the fence, and prevents new writer registration

#### Scenario: Late writer registration races freeze
- **WHEN** a writer registration races with the freeze transaction
- **THEN** exactly one ordering wins and no writer can become active under the closed generation after freeze commits

#### Scenario: Stale callback writes after freeze
- **WHEN** a callback holding the previous generation attempts a canonical commit after freeze
- **THEN** the repository rejects the commit before any canonical row, artifact, event, report, or ledger changes

#### Scenario: Session writer is admitted atomically
- **WHEN** a session has exactly one open mutation scope and a writer is admitted
- **THEN** scope selection, parent validation, generation/fence validation, and registration commit in one atomic ordering

#### Scenario: Freeze wins session writer admission
- **WHEN** freeze closes the only open scope before the atomic session writer admission commits
- **THEN** admission fails with the typed expected closed-admission reason and no writer row becomes active

#### Scenario: Open-scope cardinality is ambiguous
- **WHEN** session writer admission observes more than one open mutation scope
- **THEN** admission fails with the typed ambiguous-scope reason and MUST NOT be classified as a retryable rollover

#### Scenario: Session has never entered mutation authority
- **WHEN** a compatibility caller opens a writer turn for a session with no mutation-scope history
- **THEN** the Host preserves the existing untracked-session behavior without registering a writer

#### Scenario: Owning transaction observes an untracked session
- **WHEN** a Host-managed write transaction needs a nested writer turn and its stable transaction snapshot proves the session has no mutation-scope history
- **THEN** the Host preserves the local untracked-session behavior without opening a second writer connection or reacquiring its own SQLite write lock

### Requirement: Writer retirement is explicit and cannot be inferred from idleness
A writer MUST become retired only through an explicit fenced retirement commit or a trusted parent/process-supervisor proof that the exact process epoch and all descendants have terminated. Lease expiry, HTTP response, runtime idle, empty queue, missing thread handle, timeout, remote disconnect, or worker heartbeat loss MUST NOT be treated as writer retirement or remote-effect cancellation.

#### Scenario: Retire a completed writer
- **WHEN** a writer has committed or abandoned all permitted local mutations and all child writers are retired
- **THEN** it records fenced retirement and leaves the active writer set

#### Scenario: Lease expires while callback may still run
- **WHEN** a writer lease expires but its process or callback has not been proven terminated
- **THEN** the scope remains non-quiescent and any late canonical commit remains fenced

#### Scenario: Local process termination does not cancel HPC
- **WHEN** a trusted parent proves a local worker process epoch has terminated after remote dispatch
- **THEN** the local writer may retire but the external operation retains its independent effect/reconciliation state

### Requirement: Local process settlement is distinct from scope quiescence
The Host MUST distinguish a mutation scope's freeze/quiescence/seal lifecycle from the local process-settlement proof used to hand a root back after an exact process epoch retires. Local settlement MUST require zero active registered writers and a stable bounded authority snapshot, but it MUST NOT require every scope to be terminal. It MUST NOT issue a scope quiescence receipt, seal a scope, or infer workflow completion.

#### Scenario: Writer-free open scope is handed off
- **WHEN** an exact child process epoch has retired, the bounded mutation-authority snapshot is stable, and a nonterminal scope contains no active writers
- **THEN** local settlement may succeed while the scope remains unchanged for later fenced writer admission

#### Scenario: Active writer blocks local settlement
- **WHEN** any writer in the bounded authority snapshot remains `registered` or `retiring`
- **THEN** local settlement fails and cannot be upgraded by process idleness or a terminal task

#### Scenario: Local settlement is observed twice
- **WHEN** child and parent independently project the same canonical authority rows around exact process retirement
- **THEN** both projections yield the same bounded digest without mutating authority state

#### Scenario: Product topology is malformed
- **WHEN** local writers are zero but the current scope has an invalid product identity, parent, kind, or lifecycle relationship
- **THEN** local settlement remains only a process fact and the responsible product/Core projection rejects the topology

### Requirement: Quiescence requires complete and stable canonical state
The Host MUST issue quiescence only when new writer admission is closed, the complete registered active writer set is empty, every covered write path enforces the current fence, durable event/outbox and SQLite state have reached stable recorded high-watermarks, and artifact publications are atomically complete. Runtime idle, task terminal, capability terminal, or successful shutdown alone MUST NOT satisfy this requirement.

#### Scenario: Reach quiescence normally
- **WHEN** all registered writers and descendants retire under the freeze generation and covered high-watermarks remain stable
- **THEN** the scope may enter `quiescent` and record the exact writer-set and state digests

#### Scenario: A writer remains active
- **WHEN** any registered writer, child process, callback, or publisher has not retired
- **THEN** the scope remains `freezing` or fails closure and no quiescence receipt is issued

#### Scenario: State changes during final verification
- **WHEN** a covered high-watermark or artifact set changes between quiescence checks
- **THEN** the Host rejects the candidate receipt and re-evaluates the active generation

### Requirement: Quiescence receipts are immutable and offline-verifiable
A successful quiescence transition MUST create one immutable receipt bound to the scope id, seal generation, policy and coverage digests, complete writer-set/terminal-proof digest, SQLite/event/artifact high-watermarks, snapshot digest, and issue time. A verifier MUST be able to recompute the receipt from sealed bounded evidence without trusting mutable workspace projection.

#### Scenario: Issue a valid receipt
- **WHEN** all quiescence invariants hold for one scope generation
- **THEN** the Host stores one immutable receipt whose digests reproduce the exact closure state

#### Scenario: Detect a modified receipt or snapshot
- **WHEN** a receipt field, writer proof, high-watermark, or sealed snapshot byte is changed
- **THEN** offline verification fails and the receipt cannot authorize sealing or GO evidence

#### Scenario: Repeat receipt issuance
- **WHEN** the same generation is asked to issue a receipt again
- **THEN** the Host returns the existing immutable identity or rejects the duplicate instead of creating divergent receipts

### Requirement: Sealing consumes exact quiescence authority and rejects post-seal mutation
The Host MUST seal only the exact quiescent scope generation referenced by a valid receipt. Sealing MUST be monotonic and MUST close all covered canonical mutation for that generation. A sealed generation MUST never be reopened; follow-up work requires a new scope or generation with a new identity and cannot rewrite the sealed snapshot.

#### Scenario: Seal a quiescent generation
- **WHEN** an authorized caller presents the exact valid quiescence receipt for a quiescent scope
- **THEN** the Host atomically marks that generation sealed and binds the sealed evidence to the receipt digest

#### Scenario: Attempt to seal without quiescence
- **WHEN** a scope is open, freezing, failed, or has no matching valid receipt
- **THEN** sealing fails closed and no eligible evidence is published

#### Scenario: Attempt a canonical write after seal
- **WHEN** any old or current writer attempts a covered canonical mutation after the generation is sealed
- **THEN** the write is rejected and the sealed snapshot remains byte- and identity-stable

#### Scenario: Start legitimate follow-up work
- **WHEN** work must continue after a generation was sealed
- **THEN** the Host creates a new explicitly linked scope/generation rather than reopening or mutating the old one

### Requirement: Failure closure never fabricates quiescence
If writer coverage is incomplete, a writer cannot retire, a process identity is ambiguous, a high-watermark is unstable, or a late write is detected, the Host MUST fail closure or remain non-quiescent. It MUST NOT create a normal eligible seal, infer success from process termination, or read racing state as final evidence. Parent-owned fatal evidence, when supported, MUST be clearly distinct from a normal quiescence receipt.

#### Scenario: Writer cannot be retired
- **WHEN** a same-process writer remains permanently blocked or its descendants cannot be proven absent
- **THEN** the Host withholds normal quiescence and the attempt remains non-eligible

#### Scenario: Late mutation is observed
- **WHEN** a covered writer attempts or completes an unauthorized post-freeze mutation
- **THEN** closure fails with a stable blocker and cannot be upgraded to a normal seal by recomputing later state

#### Scenario: Parent kills a local child
- **WHEN** a future process supervisor terminates a child after a deadline
- **THEN** that fact can prove local writer retirement only and does not prove external effect outcome or normal success

### Requirement: Quiescence does not become workflow or task truth
Mutation scope, writer, receipt, and seal states MUST express only mutation authority and closure evidence. They MUST NOT create, reorder, complete, fail, block, cancel, or resume tasks; infer report quality; choose an agent plan; or replace session/task/lane/approval/protocol truth. Agent strategy MUST remain free inside the faithfully projected constraints.

#### Scenario: Seal after a capability succeeds
- **WHEN** a capability result is durable and its mutation scope seals successfully
- **THEN** the task remains nonterminal until an agent explicitly chooses `task.finish` or another documented business transition

#### Scenario: Closure fails
- **WHEN** a mutation scope cannot prove quiescence
- **THEN** the Host projects the closure blocker as evidence and does not mechanically select a replacement scientific action

### Requirement: Quiescence projection is bounded and private authority stays hidden
Public APIs, events, workspace, evidence summaries, and health surfaces MUST expose only stable scope/receipt ids, closed lifecycle state, generation-safe digests, timestamps, writer counts by safe category, and bounded blocker codes. They MUST NOT expose mutation tokens, fencing values, claim owners, process ids, thread handles, control channels, Host paths, credentials, private callback payloads, or unrestricted writer metadata.

#### Scenario: Inspect an active freeze safely
- **WHEN** an operator reads a scope that is waiting for writers to retire
- **THEN** the projection shows bounded counts and safe categories without revealing writer authority or private locators

#### Scenario: Redact a hostile writer diagnostic
- **WHEN** a writer failure contains a secret, raw command, path, or unbounded exception text
- **THEN** public closure evidence contains only a sanitized stable blocker while raw detail remains Host-private
