## ADDED Requirements

### Requirement: Workspace job wire objects have one executable owner
The runner, Host adapter and domain MUST parse, validate, serialize and digest workspace-job handles, cancellation intents, cancellation receipts, observations and reconciliation receipts through one versioned executable wire contract. A side MAY wrap a validated object in its local domain type, but it MUST NOT maintain an independent field set or digest algorithm. Missing fields, extra fields, schema drift, identity drift and digest drift MUST fail closed with a detailed diagnostic before the object is persisted or used for another remote action.

#### Scenario: Round-trip a cancellation receipt
- **WHEN** the protected wrapper returns a valid closed cancellation receipt
- **THEN** runner, Host and domain independently accept the same bytes and reproduce the same receipt digest including `receipt_id`

#### Scenario: One side omits a field
- **WHEN** any response or replay record omits `receipt_id` or contains an unrecognized field
- **THEN** every consumer rejects it at response/replay validation with the same stable contract error and does not infer cancellation settlement

## MODIFIED Requirements

### Requirement: Runner supports job lifecycle operations for sbatch
For `sbatch` runs, the system MUST support exact-handle status query, bounded log retrieval and explicit cancellation. Every public lifecycle operation MUST accept only the opaque `run_id`; `job.logs` MAY additionally accept a bounded `tail_lines`. Before any lifecycle request, the runner MUST load and canonically revalidate the persisted RunSpec, dispatch intent, external-job handle and relevant receipt for that run. It MUST reject raw scheduler ids, remote paths, inline RunSpecs, missing records, index-only matches, extra/missing fields, digest drift and identity-mismatched records.

Cancellation MUST use the same exact handle and a frozen cancellation intent. A successful closed cancellation receipt MUST contain schema version, `receipt_id`, `cancellation_id`, `handle_id`, `cancellation_requested = true`, `terminal_settlement_proven = false`, backend receipt digest, creation time and a digest covering every preceding field. The receipt proves request acceptance only; job terminal state MUST still come from authoritative observation. Response loss or restart MUST reconcile the same cancellation/handle identity and MUST NOT issue a replacement submission or cancellation.

#### Scenario: Status polling returns queued running or terminal state
- **WHEN** a caller queries a submitted job through a valid opaque run id
- **THEN** the runner revalidates the exact handle and returns safe queued, running, completed, failed or unknown observation facts

#### Scenario: Cancel requests the same job
- **WHEN** an authorized caller submits a valid cancellation intent
- **THEN** the runner invokes cancellation for the same validated handle, returns a canonical receipt containing `receipt_id`, and continues to require observation for terminal settlement

#### Scenario: Cancellation response is lost
- **WHEN** the backend may have accepted cancellation but the response is unavailable
- **THEN** the runner records the exact cause and reconciliation requirement, performs no replacement cancel or submit, and never reports terminal cancellation without observation

#### Scenario: Lifecycle survives service restart
- **WHEN** a caller polls or cancels with a valid run id after runner restart
- **THEN** the runner revalidates the matching RunSpec, handle, dispatch/cancellation receipts, source identity, workspace generation and original deadline before using them

#### Scenario: Replay handle is tampered
- **WHEN** a persisted handle file is found by index but fails canonical schema, digest or frozen dispatch identity
- **THEN** lifecycle fails with an integrity diagnostic and performs no backend query or replacement dispatch

### Requirement: Runner captures and returns diagnostics
The runner MUST capture private diagnostics sufficient for exact triage, including operation/run/dispatch phase, effective command and resources, transport/wrapper exception chain, return code, bounded raw stdout/stderr, private handle/receipt identities and persistence location. Its public response MUST contain a stable error code, safe phase, authorized opaque identities, effect certainty, retry/reconciliation rule, mutation/fallback facts, bounded sanitized cause chain and diagnostic identity. Public output MUST omit target/user, credential, ControlPath, private path, raw command, raw scheduler/process handle, private receipt contents and unbounded logs.

#### Scenario: Known failure signature is normalized
- **WHEN** stderr matches a configured failure signature
- **THEN** the runner returns the corresponding stable code and phase while preserving bounded raw evidence privately

#### Scenario: Wrapper returns an invalid receipt
- **WHEN** a protected wrapper succeeds at the process boundary but returns malformed or identity-drifting JSON
- **THEN** the runner reports response validation with expected/observed safe facts, chooses effect certainty from the invocation phase, chains the parser cause, and does not downgrade it to a generic rejection

#### Scenario: Diagnostic text contains private data
- **WHEN** SSH or Slurm text includes target, remote path, raw handle or credential material
- **THEN** the public response redacts those values while retaining the diagnostic identity and stable error code
