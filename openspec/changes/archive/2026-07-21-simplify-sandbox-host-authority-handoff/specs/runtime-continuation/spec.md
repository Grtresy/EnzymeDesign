## MODIFIED Requirements

### Requirement: Result delivery is exact, fenced, and idempotent
Once an immutable controlled-operation result is ready, a continuation delivery worker MUST claim the exact continuation with an independent lease and fencing token, verify the result and process epoch, and deliver the bounded result or failure at most once per delivery generation. The system MUST persist delivery outcome separately from external-effect outcome and MUST enqueue an owner-agent wakeup only after the sandbox/tool invocation reaches its own durable terminal or recovery state.  Delivery to an attached process MUST leave that process's sandbox Host-call context unchanged, so later SDK calls use sandbox-process authority rather than the originating session lease or the completed continuation-delivery lease.

#### Scenario: Resume an attached SDK call
- **WHEN** a matching result is ready and the attached process epoch is alive
- **THEN** one fenced delivery sends the result to the original control channel and later duplicates reuse the persisted delivery outcome

#### Scenario: Fence a late delivery worker
- **WHEN** a newer continuation fence exists before an old worker writes its delivery result
- **THEN** the old worker cannot modify canonical continuation, sandbox, invocation, artifact, event, or wakeup state

#### Scenario: Wake after sandbox terminal
- **WHEN** result delivery lets the sandbox continue and the sandbox run then reaches terminal state
- **THEN** the system records capability outcome ready and enqueues one stable owner-agent wakeup without completing the task

#### Scenario: Call the Host again after delivery
- **WHEN** resumed code in the same attached sandbox invokes a subsequent non-effect SDK call such as `hpc.fetch_outputs`
- **THEN** the call succeeds or fails according to current sandbox-process and mutation authority without consulting or reviving the released originating session lease
