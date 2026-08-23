## ADDED Requirements

### Requirement: Adopted external capability facts preserve exact qualification-unit identity
Any target/provider resource fact derived from external qualification MUST bind capability, operation, route, subject identity, source digest, build digest, configuration digest, qualification spec/validator identity, receipt digest and validity interval. The inventory MUST NOT broaden one observed operation into a capability-wide fact or reuse evidence across route, target/provider or digest drift.

#### Scenario: Only hmmbuild was observed
- **WHEN** qualification succeeds for `hmmbuild` but not `hmmsearch`
- **THEN** the adopted fact can satisfy only the exact hmmbuild operation

#### Scenario: Target image build changes
- **WHEN** the current build digest differs from the qualification unit
- **THEN** the old fact is stale and no route requiring that build is supplied

### Requirement: Qualification freshness and revocation fail closed per unit
Inventory adoption and capability resolution MUST reject expired, failed, revoked, duplicate, schema-invalid or identity-drifted qualification receipts independently for each unit. Rejection MUST preserve other exact valid routes but MUST NOT retry, substitute another subject or silently retain the previous fact for the rejected unit.

#### Scenario: Provider receipt expires during a Session
- **WHEN** a later affordance observation finds the receipt past `valid_until`
- **THEN** the route is omitted or blocked with `blocked_qualification`, while the pinned product bundle remains unchanged
