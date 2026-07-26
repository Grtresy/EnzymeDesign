# live-attempt-supervision Specification

## Purpose
Define the local POSIX process boundary, retirement proof, root-read gate, supervision receipt, and fatal evidence required before an AOX live attempt can contribute campaign evidence.

## Requirements
### Requirement: One spawned child owns all mutable attempt state
Each live campaign attempt MUST run in a fresh `spawn` child with a dedicated process session/group and exact parent-created attempt identity. The child and its descendants MUST be the only live owners of attempt SQLite, artifact, blob, sandbox, evidence-result, and private-log mutation. The parent MUST NOT open or read those roots while that process identity or any descendant remains live.

#### Scenario: Start an isolated attempt
- **WHEN** the live campaign admits a new positive or fault attempt
- **THEN** the supervisor starts one spawn child in a dedicated process group and binds it to the exact campaign, attempt, root, nonce, and process epoch

#### Scenario: Reject a parent read before retirement
- **WHEN** parent code attempts to open the child result or another attempt root while the child is live
- **THEN** the lifecycle gate rejects and audits the access without reading the target

### Requirement: Lifecycle frames are closed, bounded, and hash chained
The child MUST report lifecycle through a versioned, size-bounded canonical-JSON protocol whose frames bind exact campaign/attempt identity, parent and child nonces, process epoch, monotonic sequence, payload digest, previous-frame digest, and frame digest. Current live execution MUST use `child_started`, `settling_local_state`, `local_state_settled`, and `child_terminal`. Unknown types or fields, noncanonical encodings, sequence gaps, duplicate conflicts, nonce/epoch drift, oversize frames, hash mismatch, or a legacy live schema MUST fail closed.

#### Scenario: Accept one exact current frame chain
- **WHEN** a matching child sends the four current `@3` lifecycle frames with contiguous valid digests
- **THEN** the parent records the final sequence and digest without treating the channel as scientific data or product truth

#### Scenario: Reject a forged or truncated chain
- **WHEN** a frame is malformed, oversized, out of order, identity-drifted, or the channel closes before required terminal frames
- **THEN** normal evidence is forbidden and the child process group enters bounded fatal retirement

#### Scenario: Preserve a frozen legacy frame chain
- **WHEN** an offline verifier reads an already sealed `@1` or `@2` lifecycle identity
- **THEN** the legacy contract remains reproducible but cannot authorize a new live child

### Requirement: Normal evidence requires local settlement and OS retirement
The supervisor MUST return child evidence to the campaign only after a matching local-settlement and terminal frame, zero active local mutation writers, a bounded canonical mutation-authority snapshot, successful SQLite checkpoint/integrity and declared-root sync, zero child exit, OS-confirmed leader retirement, an empty dedicated process group, a parent post-retirement snapshot equal to the child snapshot, and a child-result digest matching the protocol. A nonterminal mutation scope MUST be recorded but MUST NOT by itself be classified as a live local writer or product failure. A child settlement frame or leader exit alone MUST NOT establish eligibility.

#### Scenario: Complete a normal isolated attempt
- **WHEN** the child closes its Host and writers, syncs local state, emits the exact terminal chain, exits zero, leaves no descendants, and the parent reproduces its bounded settlement snapshot
- **THEN** the parent retires the root gate, verifies the sealed child result, and returns a current process-supervision receipt

#### Scenario: Preserve a legal post-closure scope
- **WHEN** SQLite contains one deterministic writer-free post-closure session scope after the attempt scope sealed
- **THEN** local process settlement succeeds while a separate Core/product projection remains responsible for validating that scope topology

#### Scenario: Reject an active writer
- **WHEN** any mutation writer remains `registered` or `retiring`
- **THEN** local settlement fails with a stable typed blocker and no normal receipt is produced

#### Scenario: Detect post-retirement snapshot drift
- **WHEN** the parent's bounded read-only mutation-authority snapshot differs from the child settlement frame after the exact process group retires
- **THEN** the attempt is fatal and the parent does not seal normal evidence

#### Scenario: Detect a descendant after leader exit
- **WHEN** the leader exits but another process remains in its dedicated group
- **THEN** the attempt is fatal, the descendant is retired within the termination bound, and no attempt bundle is produced

### Requirement: Current live receipts are versioned without weakening frozen evidence
New live attempt composition MUST require the current supervision protocol and receipt schema. Frozen `@1/@2` receipts MAY remain available only through exact offline historical validation. A current receipt MUST bind the local-settlement snapshot digest and MUST NOT be lossily transformed into a legacy receipt for current bundle acceptance.

#### Scenario: Start a new live attempt with a legacy schema
- **WHEN** launch composition or qualification selects supervision `@1` or `@2`
- **THEN** it fails before model construction, attempt-root creation, or external effect

#### Scenario: Validate frozen legacy evidence
- **WHEN** an offline historical verifier is explicitly evaluating a sealed legacy bundle
- **THEN** it applies the exact historical validator without upgrading or changing the receipt

#### Scenario: Build a current bundle
- **WHEN** a newly produced live result contains a valid `@3` receipt
- **THEN** every current validator consumes that exact receipt and no compatibility path down-projects it to `@1`

### Requirement: Fatal retirement is finite and cannot manufacture closure
On parent deadline, protocol failure, missing quiescence, nonzero exit, result mismatch, or descendant leak, the supervisor MUST apply a bounded exact-group `SIGTERM` then `SIGKILL` ladder, reap the leader, and test group retirement. It MUST NOT return while a provably targeted local writer remains merely because an HTTP call or Python thread timed out.

#### Scenario: Retire a permanently blocked child
- **WHEN** the child ignores cooperative shutdown and remains alive past the attempt deadline
- **THEN** the parent terminates and reaps the exact attempt group within the configured hard bound and reports a stable timeout blocker

#### Scenario: Retirement cannot be proven
- **WHEN** the platform cannot prove the exact child group and descendants are retired
- **THEN** the attempt remains fatal and non-eligible, roots remain unread, and the blocker states that descendant retirement is unproven

### Requirement: Parent fatal evidence is separate and non-eligible
After local retirement, a fatal attempt MUST produce one append-only parent-owned artifact outside the attempt root. The closed artifact MUST record safe lifecycle facts and MUST set `cutover_eligible=false`, `ledger_after_claimed=false`, `sqlite_closure_claimed=false`, and `artifact_completeness_claimed=false`. It MUST NOT contain credentials, private paths, raw errors, backend locators, or reconstructed product state, and the campaign MUST NOT seal a normal attempt bundle from the partial child root.

#### Scenario: Seal timeout evidence
- **WHEN** bounded retirement follows an attempt timeout
- **THEN** the parent writes a digest-checked fatal artifact with the termination ladder and last valid frame facts, then stops the campaign

#### Scenario: Preserve an unknown remote outcome
- **WHEN** the child may have submitted a provider or HPC effect before dying and no exact reconciliation proof is available
- **THEN** fatal evidence records the external outcome as unknown, makes no cancellation claim, and forbids the next campaign attempt

### Requirement: Supervision does not own product decisions
The process supervisor MUST NOT resolve approval, dispatch or retry an operation, call a provider or runner, cancel remote work, mutate task/report state, choose a scientific fallback, or interpret process exit as a business terminal state. The child MUST continue to run the canonical public Host/product path.

#### Scenario: Child dies with product work in flight
- **WHEN** the supervised process exits or is killed while canonical work is nonterminal
- **THEN** the parent records only harness-fatal lifecycle facts and leaves product/remote outcome unknown rather than writing a task or operation decision

### Requirement: The live CLI requires process supervision
The `run-live` campaign entry MUST invoke the live attempt runner only through the process-isolated supervisor and MUST require a valid supervision receipt before sealing a bundle-producing attempt. Ordinary `AoxCutoverCampaign` construction MUST require the same receipt by default. Direct same-process runner invocation MAY remain available only through the explicitly named `AoxCutoverCampaign.for_non_live_test(...)` fixture seam for focused non-live tests and MUST NOT be the numbered campaign entry.

#### Scenario: Compose a live campaign
- **WHEN** the operator starts `run-live` from pinned declarations
- **THEN** both positive and fault attempt runners are the same process-isolated wrapper with fixed deadline and termination bounds

#### Scenario: Supervision receipt is missing
- **WHEN** a runner returns apparent scientific evidence without the required exact supervision receipt
- **THEN** the live campaign fails closed before ledger-after sealing or attempt-bundle publication

#### Scenario: Construct an unisolated fixture campaign
- **WHEN** a focused non-live test intentionally uses a direct runner without process supervision
- **THEN** it must call the explicitly named non-live test constructor while the ordinary constructor remains supervision-required
