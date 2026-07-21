## MODIFIED Requirements

### Requirement: Execution leases are independent and fenced
The system MUST claim controlled-operation work with an execution-specific lease, monotonically increasing fencing token, and optimistic state version. The system MUST NOT use a session runtime lease, agent signal claim, sandbox process lease, continuation-delivery lease, or mutation seal token as execution authority. External calls MUST occur outside SQLite transactions, and every canonical callback commit MUST compare the current execution lease, fence, state version, and mutation authority in the same transaction.  An engine callback made for durable work MUST receive a typed sandbox Host-call context bound to that exact execution and its current repository connection; it MUST NOT recover authority from an engine-captured session scope or optional repository override.

#### Scenario: Execute without a session lease
- **WHEN** an approved operation waits on a provider or HPC backend
- **THEN** the execution worker can retain or renew only its execution lease while the session runtime lease remains free for other bounded agent turns

#### Scenario: Fence a stale callback
- **WHEN** an execution lease expires, a higher fencing token is issued, and the old worker later receives a backend response
- **THEN** the old worker cannot update canonical execution, result, artifact, event, or task state

#### Scenario: Avoid a long database transaction
- **WHEN** an execution worker performs a slow dispatch, poll, or result fetch
- **THEN** no SQLite transaction remains open across the external wait and the subsequent commit revalidates its authority

#### Scenario: Reject a mismatched execution context
- **WHEN** a durable adapter callback receives a Host context for another execution, session, state version, or fence
- **THEN** it fails before dispatch or canonical mutation and does not fall back to session-turn or sandbox-process authority
