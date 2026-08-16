## ADDED Requirements

### Requirement: Supervision consumes canonical product lifecycle
The live supervisor MUST consume the Core-derived scientific attempt lifecycle and readiness
evaluation for the exact attempt. It MUST NOT infer terminal or readiness truth from a mutable base
attempt status, a local report-status subset, or an independently reconstructed event window.

#### Scenario: Immutable closure already exists
- **WHEN** the canonical derived lifecycle proves the exact attempt is closed while its base attempt row retains a historical pre-closure status
- **THEN** supervision treats the attempt as closed and does not emit a false runtime-drain or missing-control failure

#### Scenario: Canonical evaluation is nonterminal
- **WHEN** the shared evaluation proves closure prerequisites remain incomplete
- **THEN** supervision preserves the nonterminal state without manufacturing terminal success

### Requirement: Fatal supervision evidence preserves causal identity
The live supervisor MUST preserve the earliest error identity and bounded causal chain in the fatal
artifact and campaign decision when a typed child/runtime error already exists. Wrapper codes MAY
describe process or campaign containment but MUST NOT become the only projected cause.

#### Scenario: Child runtime exposes a typed root failure
- **WHEN** the child exits after persisting a typed runtime failure
- **THEN** the parent fatal artifact binds that root code/reference together with the child-exit wrapper

#### Scenario: Child dies without typed product evidence
- **WHEN** the process terminates before any safe typed root failure is persisted
- **THEN** the supervisor records its own process-lifecycle cause without claiming a product diagnosis
