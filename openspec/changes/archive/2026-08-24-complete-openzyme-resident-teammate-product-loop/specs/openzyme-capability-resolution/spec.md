## ADDED Requirements

### Requirement: Model tool exposure is Direct, Deferred or Hidden
For every declared tool and every admitted role/turn, the selected Distribution SHALL provide one digest-bound exposure decision: `Direct`, `Deferred` or `Hidden`. Exposure is presentation policy and MUST remain orthogonal to capability availability, authority, approval, qualification, workspace readiness and route selection.

#### Scenario: Build a Direct collaboration list
- **WHEN** a ready master turn is admitted
- **THEN** stable collaboration verbs and declared role essentials that are currently callable appear directly in the model function list

#### Scenario: Classify a long-tail Plugin tool
- **WHEN** an available Plugin tool is not essential for the role
- **THEN** it is Deferred and is absent from the initial function list while remaining safely inspectable

#### Scenario: Hide a forbidden tool
- **WHEN** role policy classifies a tool Hidden
- **THEN** neither provider tools nor capability inspection disclose its identity or contract

### Requirement: Exposure policy covers the exact declared catalog
The role policy SHALL cover every exact declared catalog entry and produce a `ToolExposureSnapshot@1` bound to Session/member/turn, subject policy, catalog, affordance and authority identities. Missing, duplicate, unknown or stale decisions MUST fail runtime admission.

#### Scenario: Plugin adds a new tool without policy
- **WHEN** a Distribution activates a catalog containing an entry absent from the role policy
- **THEN** startup or runtime admission fails closed rather than defaulting it Direct or Deferred

#### Scenario: Policy names an absent tool
- **WHEN** role policy contains a tool not in the adopted declared catalog
- **THEN** composition validation rejects the policy/catalog drift

#### Scenario: Role policy changes during a Session
- **WHEN** the exposure policy digest differs from the Session's adopted release/binding identity
- **THEN** the current turn is rejected and a new policy is not silently adopted

### Requirement: Capability inspection expands only exact Deferred tools
`capabilities.inspect` SHALL expose public-safe metadata and blockers for non-Hidden tools and MAY expand only caller-named, currently available Deferred tools for the remainder of one command. Expansion MUST NOT mint authority, satisfy approval, clear qualification, change target/route or make a blocked tool callable.

#### Scenario: Discover Deferred capabilities
- **WHEN** the model invokes inspection without expansion names
- **THEN** it receives bounded Deferred tool descriptions, requirements and blockers without Hidden entries

#### Scenario: Expand an available Deferred tool
- **WHEN** the model names an exact Deferred tool whose affordance is available
- **THEN** the command-scoped exposure adds the tool and preserves the original affordance/route identities

#### Scenario: Expand a blocked Deferred tool
- **WHEN** the model names a Deferred tool blocked by authority, approval, provisioning or qualification
- **THEN** inspection reports the blocker and the provider function list does not make it callable

### Requirement: Dispatch always revalidates affordance after exposure
Every tool invocation SHALL be checked against the original catalog, current authority/workflow epoch, workspace generation, approval, capability proof, health and exact selected route even if the tool is Direct or was expanded from Deferred. Exposure MUST NOT be accepted as execution authority.

#### Scenario: Route becomes unavailable after expansion
- **WHEN** a Deferred tool was expanded and its exact route becomes unavailable before dispatch
- **THEN** dispatch returns the current structured blocker without selecting an adjacent route

#### Scenario: Authority is revoked after prompt construction
- **WHEN** a Direct tool remains in the provider schema but current authority no longer permits it
- **THEN** dispatch rejects the invocation and records no tool effect
