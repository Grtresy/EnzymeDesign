## ADDED Requirements

### Requirement: Terminal acceptance composes product rollover and process retirement
A completed supervised scientific closure MUST be accepted only when the Core terminal-rollover projection proves `post_closure_scope_open` for the exact attempt and an independent current supervision receipt proves local writer settlement and exact process-group retirement. Neither proof MUST substitute for the other.

#### Scenario: Legal rollover and local retirement agree
- **WHEN** the attempt scope is sealed, the exact deterministic post-closure session scope is the only open scope, active writers are zero, and the supervised process group has retired
- **THEN** the closure evidence may satisfy the combined terminal handoff requirement

#### Scenario: Process retires with malformed product topology
- **WHEN** local process settlement succeeds but the post scope has a wrong identity, parent, kind, state, or competitor
- **THEN** scientific closure evidence fails through the Core rollover projection

#### Scenario: Product closure exists while a writer remains live
- **WHEN** the Core rollover projection is valid but the supervision settlement still contains an active writer or descendant
- **THEN** scientific closure evidence remains ineligible and product closure is not rewritten

#### Scenario: Supervisor observes a legal open scope
- **WHEN** the only nonterminal scope is the Core-proven deterministic post-closure scope
- **THEN** the supervisor records its bounded identity digest without treating scope openness as process activity
