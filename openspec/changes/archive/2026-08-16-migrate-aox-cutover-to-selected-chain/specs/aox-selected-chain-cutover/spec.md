## ADDED Requirements

### Requirement: AOX selected-chain evidence uses schema version three
New selected-chain AOX attempts SHALL emit `aox_blank_world_attempt_bundle@3` and SHALL be verified only by the exact `@3` verifier. The system MUST retain the historical `@2` verifier and MUST NOT upgrade, reinterpret, backfill, or combine `@2` attempts with `@3` selection records.

#### Scenario: Verify a new selected-chain bundle
- **WHEN** a sealed bundle declares the exact `@3` schema and all required records
- **THEN** the verifier applies only selected-chain rules and reports the exact verifier version

#### Scenario: Present a historical bundle
- **WHEN** an r48-r51 or other `@2` bundle is inspected
- **THEN** it remains frozen under the historical verdict and no new adoption record can make it eligible

### Requirement: The bundle seals universe, selection, authority, and closure
An `@3` bundle MUST contain bounded sealed evidence for the Host-derived operation/run universe, every disposition, adopted role mapping, effect adoption, artifact materialization, selection revision/seal, attempt authorization consumption, quiescence receipt, attempt closure, AOX branch derivation, approval, report, workspace/UI interaction, and complete artifact/digest lineage.

#### Scenario: Recompute an eligible bundle offline
- **WHEN** an offline verifier receives only the declared sealed bundle contents
- **THEN** it can recompute the operation universe, unique adopted chain, branch, identities, digests, authority and closure without online provider access or mutable workspace trust

#### Scenario: Tamper with a disposition
- **WHEN** a disposition, materialization receipt, universe member, envelope consumption, or closure digest changes
- **THEN** offline verification fails and the attempt cannot contribute GO evidence

### Requirement: One adopted operation satisfies each reached AOX role
For the branch derived from sealed AOX scientific artifacts, each reached required workflow role SHALL have exactly one adopted operation whose inputs, outputs, provider/backend, source, approval, and downstream lineage satisfy the versioned contract. Optional omitted roles MUST be justified by recomputed branch facts; every non-adopted occurrence MUST have a legal disposition.

#### Scenario: Repair a role after known failure
- **WHEN** one no-effect operation fails and a later same-attempt operation satisfies that role
- **THEN** the agent may mark the first `failed`, adopt the replacement, and pass only if both occurrences and the final lineage verify

#### Scenario: Two successful occurrences exist
- **WHEN** two completed operations could satisfy one role
- **THEN** exactly one must be adopted and the other explicitly superseded or otherwise legally disposed

### Requirement: AOX can continue across runs only through same-attempt adoption
An AOX formal attempt MAY span multiple sandbox runs and local repair paths. A later run SHALL consume an earlier known effect only through a valid same-attempt, same-scope adoption and Host materialization receipt; mutable checkpoints, shared paths, report text, or equal bytes MUST NOT authorize continuation.

#### Scenario: Adopt an upstream provider result after local parser failure
- **WHEN** an upstream effect completed correctly before a local run failed and all effect/artifact facts are known
- **THEN** a repaired run in the same formal attempt may materialize that effect and continue without replaying the provider

#### Scenario: Try to reuse another positive attempt
- **WHEN** a positive attempt references an artifact from another positive, probe, fault, campaign, or historical root
- **THEN** the verifier and driver reject it regardless of digest equality

### Requirement: AOX admission is safety based rather than failure-count based
Before each controlled dispatch, the AOX driver SHALL require active attempt authority, available envelope resources, valid source/materialization lineage, compatible replacement policy, closed prior effect state, and valid process/writer authority. A known terminal disposed failure or prior extra occurrence MUST NOT be an automatic blocker, while unknown effect, active/unretired work, missing disposition authority, or permission/resource breach MUST block dispatch.

#### Scenario: Continue after a disposed local failure
- **WHEN** a prior operation is terminal `no_effect`, the agent records a legal failure disposition, and authority remains
- **THEN** the driver may admit a replacement operation without treating the whole attempt as poisoned

#### Scenario: Prior effect is unknown
- **WHEN** any prior operation in the attempt is `dispatch_in_doubt`
- **THEN** the driver stops before approval or dispatch and requires reconciliation

### Requirement: AOX final GO evidence remains strict and independent
Selected-chain semantics MUST NOT reduce the cutover requirement for two independent positive attempts and one fail-closed fault attempt under the same pinned commit/config, real approval/UI evidence, blank-world isolation, MICU/resource compliance, complete report/evidence artifacts, and zero cross-attempt reuse. Intermediate trial and error MAY be excluded only from the adopted chain after complete lawful disposition.

#### Scenario: One positive passes after internal repair
- **WHEN** one positive attempt closes with a valid adopted chain after known trial and error
- **THEN** it counts as at most one positive and cannot supply evidence to the second positive or fault attempt

#### Scenario: A known failure is hidden
- **WHEN** a bundle omits a failed run or operation because it was not adopted
- **THEN** universe verification fails and the attempt is ineligible

### Requirement: Non-live recovery qualification precedes the next numbered attempt
The repository SHALL provide non-live qualification covering cross-run adoption, explicit supersession, known no-effect replacement, unknown-effect fail closed, process/writer closure, envelope limits and concurrency, schema tamper, and historical `@2` freezing. Documentation MUST record readiness only after focused tests, non-live eval, UI tests/build, and mainline gates pass, and MUST NOT claim live GO or start a numbered attempt.

#### Scenario: Complete implementation qualification
- **WHEN** every non-live gate passes for `@3`
- **THEN** the change records “ready before next numbered live attempt” and leaves live campaign state untouched

#### Scenario: A qualification gate fails
- **WHEN** any required non-live recovery, verifier, UI, or mainline check fails
- **THEN** readiness is withheld and no live attempt is started as a workaround
