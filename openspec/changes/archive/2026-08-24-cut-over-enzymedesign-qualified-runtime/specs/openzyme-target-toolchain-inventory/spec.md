## ADDED Requirements

### Requirement: Deployment adoption ledger is exact, current and profile-bounded
The deployment MUST persist an immutable adoption ledger containing exactly one fact for every current Batch 1 qualification unit, each bound to its receipt, source compatibility proof, cutover plan and authority. Startup and every later admission MUST reject expired or drifted facts per unit. AlphaFold MUST remain represented as deferred/non-qualified/not-adopted and MUST NOT appear in effective inventory or affordances.

#### Scenario: Adopted Provider fact expires after cutover
- **WHEN** runtime admission occurs after the fact's `valid_until`
- **THEN** the exact Provider route becomes `blocked_qualification` without changing the product bundle or selecting a fallback

