## ADDED Requirements

### Requirement: Scientific workflow contracts close every enforced role constraint
Each scientific workflow contract admitted for a new attempt SHALL have a canonical public-safe preimage and digest covering the contract schema and id, workflow id, attempt scopes, declared workflow roles, every role's closed SDK operation signatures, cardinality policy, effect/adoption policy, and same-attempt reuse policy. A validator MUST NOT enforce a role-to-operation rule that is absent from the digest-bound preimage.

#### Scenario: Bind a new attempt to an exact contract
- **WHEN** the Host admits a new scientific attempt with a supported workflow id and contract digest
- **THEN** the registry resolves exactly one canonical contract whose recomputed digest equals the attempt digest before any selection or adoption mutation

#### Scenario: Change a role operation signature
- **WHEN** a role-to-SDK-module/function mapping changes while all role names remain the same
- **THEN** the canonical contract digest changes and the old digest cannot authorize validation under the changed mapping

#### Scenario: Reject an unsupported contract identity
- **WHEN** an attempt references an unknown workflow id, contract id, schema version, or digest
- **THEN** selection/adoption validation fails closed without selecting a nearby contract or falling back to a callable validator

### Requirement: One contract source drives validation and constraint projection
The Host SHALL derive allowed roles, operation-compatible roles, role validation, and the agent-safe contract projection from the same resolved contract object. Contract projection and validation MUST use the attempt's exact scope and MUST NOT maintain independent role or operation maps.

#### Scenario: Project compatible roles for an occurrence
- **WHEN** an agent inspects a selection occurrence whose canonical SDK module/function matches one or more roles in the exact attempt scope
- **THEN** the projection returns those compatible role identifiers and the validator accepts exactly the same operation-role pairs

#### Scenario: Reject a role from another scope
- **WHEN** an operation is assigned a role declared only for a different attempt scope
- **THEN** validation rejects the role and returns the current scope's allowed and operation-compatible role facts

#### Scenario: Detect projection and validation drift
- **WHEN** a qualification fixture mutates either projected compatibility or validation compatibility independently
- **THEN** executable contract qualification fails before the changed contract can admit a new attempt

### Requirement: Contract observations expose constraints without choosing scientific strategy
Public contract observations SHALL contain only stable contract identity, scope, role names, closed operation signatures, cardinality/reuse constraints, and compatibility facts. They MUST NOT contain recommended actions, operation rankings, inferred adoption, provider/runner credentials or locators, Host paths, lease/fencing authority, or private diagnostics.

#### Scenario: Observe a single compatible role
- **WHEN** one occurrence is compatible with exactly one declared role
- **THEN** the Host reports that deterministic constraint but does not adopt the occurrence, create a disposition, seal the selection, or claim the task is complete

#### Scenario: Submit an invalid role alias
- **WHEN** an agent submits a plausible but undeclared alias for a compatible role
- **THEN** the Host rejects it with exact allowed/compatible role facts and does not silently rewrite the alias

#### Scenario: Inspect a contract through public tools
- **WHEN** a contract is projected through `scientific.attempt.inspect`, `world.inspect`, workspace, event, API, or UI surfaces
- **THEN** every surface remains bounded and public-safe and none acquires mutation or scientific-decision authority

### Requirement: AOX new attempts bind the complete selected-chain contract version
New AOX blank-world scientific attempts SHALL bind a selected-chain contract version whose digest covers the formal/fault and probe role sets plus each role's exact SDK operation signature. The historical selected-chain contract version SHALL remain frozen and readable for historical evidence but MUST NOT authorize a new AOX attempt.

#### Scenario: Resolve an AOX formal or fault contract
- **WHEN** a new formal or fault AOX attempt resolves its contract
- **THEN** the allowed roles are exactly `ncbi_fetch`, `reference_alignment`, `hmm_build`, `hmmer_search`, `uniprot_fetch`, `candidate_alignment`, and `cdhit`, with each role bound to its declared SDK module/function

#### Scenario: Resolve an AOX probe contract
- **WHEN** a new AOX probe attempt resolves its contract
- **THEN** the allowed roles are exactly `ncbi_fetch`, `reference_alignment`, `hmm_build`, `uniprot_fetch`, `candidate_cluster`, and `candidate_alignment`, with each role bound to its declared SDK module/function

#### Scenario: Read historical r54 contract evidence
- **WHEN** the system reads r54 or another attempt bound to the frozen historical contract
- **THEN** it preserves the original contract identity and failure evidence without upgrading, continuing, mutating, or making that attempt cutover eligible
