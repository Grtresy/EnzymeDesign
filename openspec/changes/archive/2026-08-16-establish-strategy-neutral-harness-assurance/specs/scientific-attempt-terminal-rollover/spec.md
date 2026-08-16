## ADDED Requirements

### Requirement: Scientific closure validates only mutation-owner constraints at dispatch
`scientific.attempt.close` MUST validate the exact attempt, canonical assignee, current
selection/finalization receipt, lifecycle, authority, quiescence, fencing, and mutation
scope at its owning service.  It MUST NOT depend on a generic composition hook or use
report delegation/order, assistant narration, or unrelated task timing as dispatch
authority.

#### Scenario: Close with complete owner facts
- **WHEN** the canonical assignee submits a close request whose attempt, selection, receipt, authority, and quiescence facts are valid
- **THEN** the scientific service may persist closure intent independent of reporter delegation timing or prior narration

#### Scenario: Reject a real closure violation
- **WHEN** attempt identity, assignee, selection, receipt, authority, quiescence, fence, or scope is invalid
- **THEN** the scientific owner rejects the mutation with exact typed facts and no generic workflow phase result

### Requirement: AOX product completeness cannot gate generic task and report strategy
The system MUST check AOX exact task cardinality, owner-authored finishes, source-linked report, final answer,
selected chain, and deliverable completeness MUST be checked by public product-closure
evaluation and offline verification.  They MUST NOT prevent an otherwise authorized
`task.delegate`, `task.finish`, or `report.publish` call through a session-specific
pre-dispatch policy.

#### Scenario: Report task is delegated early
- **WHEN** an authorized master delegates reporting before scientific execution is complete
- **THEN** generic delegation succeeds or fails only for task/protocol reasons and AOX remains ineligible until final facts close

#### Scenario: Published report lacks AOX closure facts
- **WHEN** a report is generically publishable but lacks current AOX source/finalization requirements
- **THEN** publication remains canonical while AOX product closure identifies the missing facts and refuses cutover eligibility
