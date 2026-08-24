## ADDED Requirements

### Requirement: Agent Git workspace provisioning is a durable asynchronous occurrence
Every fresh Agent workspace SHALL be represented by one exact reserved `WorkspaceGeneration@1` and one durable `WorkspaceProvisioningIntent@1` before Adapter work begins. The intent MUST bind the Session, member, generation, repository pin, selected provider/target and Adapter binding digest, and MUST use a bounded claim lease.

#### Scenario: Bootstrap the master workspace reservation
- **WHEN** a Distribution creates a fresh Session
- **THEN** generation 1 and its pending provisioning intent are committed atomically with the Session and no clone is executed inside the HTTP request

#### Scenario: Claim provisioning work
- **WHEN** the bounded worker claims a pending intent
- **THEN** it records one claim owner/token/epoch/expiry and invokes only the exact selected workspace Adapter

#### Scenario: Another worker races the claim
- **WHEN** two workers attempt to claim the same intent
- **THEN** exactly one owns the occurrence and the loser performs no Adapter effect

### Requirement: Workspace readiness activates runtime eligibility atomically
An Agent workspace SHALL become runtime-ready only after the selected Adapter's exact controlled-operation receipt is settled and the observed Git/volume identity matches the reserved generation. The Kernel MUST atomically create the runtime binding, activate the matching authority lease and settle the provisioning intent.

#### Scenario: Settle a valid workspace observation
- **WHEN** the Adapter returns a complete identity for the reserved generation and current claim
- **THEN** generation state advances to `READY`, member/lease generation agree, and message/runtime admission becomes eligible in one commit

#### Scenario: Observation differs from the reservation
- **WHEN** the Adapter receipt names another member, generation, repository base, provider, target or root identity
- **THEN** settlement fails before activation and records a structured identity failure

#### Scenario: Callback is duplicated
- **WHEN** the exact terminal receipt is delivered more than once
- **THEN** the existing ready settlement is returned idempotently without another clone, lease activation or event sequence

### Requirement: Provisioning blockers require explicit recovery
A provisioning failure SHALL preserve effect certainty, mutation fact, reconciliation policy, failure identity and private diagnostic provenance. The system MUST NOT automatically retry, choose another Adapter, repair Git state or create a successor generation.

#### Scenario: Clone fails before effect
- **WHEN** the Adapter proves `no_effect`
- **THEN** intent/public readiness becomes `blocked` with retry disabled until an explicit operator recovery command

#### Scenario: Clone result is uncertain
- **WHEN** the Adapter reports `dispatch_in_doubt`
- **THEN** the intent becomes `blocked` with `reconcile_required=true` and no redispatch is performed

#### Scenario: Reconcile the exact uncertain occurrence
- **WHEN** an authorized operator names the exact Session, blocked intent digest/state version and bounded claim duration
- **THEN** the Kernel creates or claims a durable `WorkspaceProvisioningReconciliation@1` that observes the original request and receipt without mutating or redispatching the blocked intent

#### Scenario: Reconciliation proves the reserved generation ready
- **WHEN** the exact observation-only reconciliation settles `ready`
- **THEN** the reserved generation/runtime binding/lease become ready atomically while the original blocked intent, dispatch receipt and failure remain immutable historical facts

#### Scenario: Reconciliation proves a terminal blocker
- **WHEN** the exact reconciliation settles `blocked` with `reconcile_required=false`
- **THEN** the public next action becomes explicit successor creation and no generation or Adapter work is created automatically

#### Scenario: Operator replaces a failed generation
- **WHEN** an authorized operator explicitly requests replacement after diagnosis
- **THEN** the Kernel creates the next monotonic generation and a new intent without mutating the historical failed occurrence
