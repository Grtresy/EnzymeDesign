## ADDED Requirements

### Requirement: External validation claims are evidence-layer exact
Qualification reports and release claims MUST separately enumerate declaration verification, runtime mounting, deterministic non-live readiness, real-subject qualification, deployment cutover and individual live occurrences. Evidence from one layer MUST NOT be phrased or serialized as proof of a later layer, and aggregate booleans MUST retain the same separation.

#### Scenario: Non-live product composition closes
- **WHEN** real Kernel, Store, Plugin runtimes and state machines run while declared external Ports use recording substitutes
- **THEN** the report may claim non-live composition/readiness closure but MUST state that external systems and software were not live-qualified

#### Scenario: One real occurrence succeeds
- **WHEN** a qualified route completes one real provider call or scheduler job
- **THEN** that occurrence is live evidence only for its exact unit and does not prove cutover or all-component qualification

### Requirement: Later lifecycle adoption requires explicit evidence type
A runtime MUST accept a `qualified` route only from an unexpired real-subject qualification receipt whose exact unit matches the current route/resource facts. A deployment MUST accept cutover only from an explicit cutover receipt. Boolean flags, mounted runtime proofs, non-live readiness receipts or test names MUST NOT substitute for either evidence type.

#### Scenario: Readiness receipt is supplied as route qualification
- **WHEN** capability binding receives a deterministic `ready_non_live` receipt
- **THEN** it rejects qualification adoption and keeps the route unavailable for qualified-only operations
