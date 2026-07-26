## MODIFIED Requirements

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

## ADDED Requirements

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
