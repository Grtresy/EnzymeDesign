## ADDED Requirements

### Requirement: Fresh attempts require a durable authorization envelope
Every formal scientific attempt SHALL be created from a durable authorization envelope or an exact one-attempt approval. The envelope MUST bind grantor, session, task, campaign/workflow, permitted scopes, maximum attempt count, MICU/cost/time ceilings, allowed effect classes, provider/HPC target allowlists, expiry, and policy digest.

#### Scenario: Agent creates an attempt within grant
- **WHEN** an agent requests a compatible attempt and the envelope has an unexpired slot and sufficient ceilings
- **THEN** the Host creates a fresh canonical attempt id/root/scope and atomically consumes one slot

#### Scenario: No envelope exists
- **WHEN** an agent requests a formal attempt without a durable envelope or exact approval
- **THEN** the Host returns `authorization_required` and does not create roots, operations, or external effects

### Requirement: Envelope consumption is atomic and idempotent
Attempt count and reserved resource consumption MUST be checked and written in one transaction using envelope version and idempotency identity. Concurrent or replayed requests MUST NOT oversubscribe count, MICU, cost, time, or target authority.

#### Scenario: Two agents race for the final slot
- **WHEN** two valid requests concurrently consume an envelope with one remaining attempt
- **THEN** exactly one attempt is created and the other receives an exhausted/version-conflict result

#### Scenario: Client retries after disconnect
- **WHEN** the same normalized request and idempotency key are repeated
- **THEN** the Host returns the original attempt identity and does not consume another slot

### Requirement: Unknown effects block subsequent attempts
An unresolved unknown external effect in the governing task/campaign authority SHALL block creation of another formal attempt even when the envelope has remaining count or budget. The blocker MUST be cleared only by canonical reconciliation or explicit terminal effect proof, not by abandonment text or a new root.

#### Scenario: Previous attempt died after dispatch
- **WHEN** the prior attempt contains an unreconciled `dispatch_in_doubt` execution
- **THEN** attempt creation fails closed and identifies reconciliation as required

#### Scenario: Known no-effect failure is closed
- **WHEN** the prior attempt failed with canonical `no_effect` and all authority/process state is closed
- **THEN** that fact alone does not block consumption of another authorized slot

### Requirement: Envelope violations never silently shrink intent
If a requested attempt exceeds expiry, resource ceilings, effect class, provider, HPC target, workflow, or scope, the Host SHALL reject it with a structured authorization fact. It MUST NOT choose a cheaper backend, omit an effect, shorten scientific scope, or modify the user's plan.

#### Scenario: Requested HPC target is not allowed
- **WHEN** the agent asks for a target outside the envelope allowlist
- **THEN** no attempt is admitted and the agent can request changed authority from the user or operator

#### Scenario: MICU reservation exceeds remaining ceiling
- **WHEN** normalized attempt reservation exceeds the remaining MICU grant
- **THEN** admission fails before provider or model work and reports the exact safe resource blocker

### Requirement: Attempt authority is projected without private grants
Public attempt projection SHALL expose stable envelope/attempt ids, allowed scope summary, consumed and remaining bounded resources, expiry, lifecycle, and blocker codes. It MUST NOT expose bearer tokens, credentials, private target locators, fencing values, or mutable Host paths.

#### Scenario: User reviews remaining attempts
- **WHEN** a user inspects the campaign authority
- **THEN** the UI reports attempt count and bounded resource status sufficient to decide whether to extend authorization
