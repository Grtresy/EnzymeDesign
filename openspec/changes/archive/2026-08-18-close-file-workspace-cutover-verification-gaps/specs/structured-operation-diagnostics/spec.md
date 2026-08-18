## ADDED Requirements

### Requirement: Every boundary failure has one detailed public-safe observation
The system MUST represent every failure crossing a public API, tool, durable execution, provider, process, persistence, cleanup, or runner boundary as a versioned structured observation. The observation MUST contain a stable `error_code`, component, operation, phase, authorized correlation identities, failure class, recoverability, effect certainty, retry eligibility, `mutation_applied`, `fallback_performed`, bounded sanitized cause chain, diagnostic identity, safe summary, and an explicit next action. A generic error string or `in_doubt` state without the specific failure source MUST NOT satisfy this requirement.

#### Scenario: Reject invalid input before effect
- **WHEN** validation rejects a workspace job request before any external invocation
- **THEN** the caller receives the exact validation code, failing phase and safe field facts with `effect_certainty = no_effect`, `mutation_applied = false`, and no retry or fallback claim

#### Scenario: Preserve a dispatch cause with uncertainty
- **WHEN** a transport exception occurs after an external dispatch may have been accepted
- **THEN** the observation records `dispatch_in_doubt` and `reconcile_required` while retaining the sanitized transport cause and exact operation/dispatch identities

### Requirement: Private diagnostics preserve the complete earliest cause
For each public failure observation, the Host or owning boundary MUST persist an immutable private diagnostic record keyed by the public diagnostic identity. The private record MUST preserve the complete exception type/message/traceback, ordered `__cause__` and `__context__`, component source, errno or return code, bounded raw stdout/stderr where applicable, private authorized path/handle facts, correlation identities, and a digest. Wrapping MUST use explicit exception chaining and MUST NOT replace the earliest specific cause with a generic boundary message.

#### Scenario: Wrap a runner parser failure
- **WHEN** the Host rejects a runner cancellation receipt because a required field is missing
- **THEN** the public observation identifies the response-validation phase and the private record retains the parser exception, missing field, response schema identity and full exception chain

#### Scenario: Inspect one diagnostic identity
- **WHEN** an authorized operator resolves the diagnostic identity from a public failure
- **THEN** the operator can inspect the immutable private record and verify its digest without exposing that record through the agent or public API

### Requirement: Catch-all handling is restricted to semantic boundaries
Production code MUST NOT silently discard an exception. A broad catch MAY exist only at an explicit boundary that determines effect certainty, persists detailed diagnostics, and either raises a typed chained exception or commits a typed durable failure state. Cleanup, rollback, best-effort observation, and compatibility projection MUST report their own failure; they MUST NOT use `pass`, bare return, an empty result, or a fabricated success to hide it.

#### Scenario: Unexpected workspace observation exception
- **WHEN** the workspace observation provider raises an exception that is not a proven Git corruption
- **THEN** recovery records an observation or infrastructure failure with the original cause and does not mark the workspace permanently corrupt

#### Scenario: Cleanup also fails
- **WHEN** a primary operation fails and cleanup of its temporary resource also fails
- **THEN** the system preserves the primary cause, records cleanup as an ordered secondary failure with the exact temporary identity, and does not report cleanup success

### Requirement: Effect certainty derives from executed phase rather than exception type
The system MUST determine effect certainty from persisted execution phase and route-specific acceptance evidence. Timeout, `OSError`, `RuntimeError`, parser failure, process death, connection loss, or lease expiry MUST NOT alone prove `no_effect`, success, cancellation, or terminal settlement. Automatic retry MUST require route-specific no-effect proof, the same idempotency identity, and a remaining finite policy budget.

#### Scenario: Same exception type at two phases
- **WHEN** the same transport exception occurs once before dispatch invocation and once after invocation begins
- **THEN** the first failure can be classified `no_effect` while the second remains `dispatch_in_doubt`, and their observations identify the different phases

#### Scenario: Reconciliation read is unavailable
- **WHEN** read-only reconciliation fails while an execution already has `dispatch_in_doubt`
- **THEN** the execution retains its existing effect certainty, records the reconciliation cause, and does not submit a replacement operation

### Requirement: Public diagnostics are detailed without leaking private authority
Public diagnostics MUST preserve stable codes, safe exception type, phase, authorized identities, expected and observed digests or counts, bounded safe cause text, effect and retry facts, and operator action. They MUST redact credentials, tokens, secret environment values, private authority/fencing values, unauthorized absolute paths, raw scheduler/SSH handles, ControlPath, hostile backend payloads, and unbounded logs. Redaction MUST be deterministic and MUST NOT remove the fields required to diagnose identity or contract drift.

#### Scenario: Backend text contains secrets and a useful code
- **WHEN** a backend exception includes a credential, remote path, raw handle, stable backend error code and receipt digest mismatch
- **THEN** the public diagnostic retains the safe error code and expected/observed digest while removing the credential, path and handle, and the private record retains the complete authorized source

#### Scenario: Sanitizer cannot classify text
- **WHEN** diagnostic text cannot be proven public-safe
- **THEN** the public observation substitutes a bounded typed redaction marker, keeps the diagnostic identity and phase, and does not expose the raw text

### Requirement: Failure observations never become workflow or effect authority
A failure observation and private diagnostic MUST remain evidence only. They MUST NOT create approval, lease, fencing, dispatch, retry, cancellation, task-terminal, scientific, publication, or fresh-install authority. Any follow-up action MUST independently satisfy its canonical contract.

#### Scenario: Agent reads a retry-looking diagnostic
- **WHEN** a failure summary suggests a transient transport cause but retry eligibility is reconciliation-required
- **THEN** the agent can inspect or reconcile the exact operation but cannot use the prose to dispatch a replacement
